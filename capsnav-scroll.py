#!/usr/bin/env python3
"""Smooth scrolling for the capsnav keyd layer.

keyd activates the empty layers `scrollup` / `scrolldown` while Caps+j / Caps+k
are held. This daemon watches those layer changes via `keyd listen` and emits a
stream of high-resolution wheel events from a virtual pointer, easing in on
press and gliding to a stop on release, so scrolling looks like a touchpad
rather than jumping one wheel notch at a time.

Speed and easing are read from CONFIG_PATH, which is re-read whenever it
changes, so edits take effect on the next scroll without a restart.

Must run as root (needs /dev/uinput and the keyd socket). No dependencies.
"""

import fcntl
import math
import os
import select
import struct
import subprocess
import sys
import time

# --- Tuning -----------------------------------------------------------------
CONFIG_PATH = "/etc/capsnav/scroll.conf"
# Defaults, used for any setting missing from CONFIG_PATH.
DEFAULTS = {
    "speed": 7.0,          # wheel clicks per second at full speed
    "ease_in_ms": 120.0,   # time to reach ~63% of full speed after pressing
    "ease_out_ms": 80.0,   # time to lose ~63% of speed after releasing
}
TICK_HZ = 120              # event rate while moving

LAYER_DIRECTION = {"scrolldown": -1, "scrollup": 1}  # wheel +1 = up

# --- uinput -----------------------------------------------------------------
EV_SYN, EV_KEY, EV_REL = 0x00, 0x01, 0x02
SYN_REPORT = 0
REL_X, REL_Y, REL_WHEEL, REL_WHEEL_HI_RES = 0x00, 0x01, 0x08, 0x0B
BTN_LEFT = 0x110
BUS_VIRTUAL = 0x06

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_DEV_SETUP = 0x405C5503   # _IOW('U', 3, struct uinput_setup), 92 bytes
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

NOTCH = 120


class VirtualWheel:
    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        # libinput only treats a device as a pointer if it has REL_X/REL_Y
        # and a button, so declare them even though they're never sent.
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_KEYBIT, BTN_LEFT)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
        for code in (REL_X, REL_Y, REL_WHEEL, REL_WHEEL_HI_RES):
            fcntl.ioctl(self.fd, UI_SET_RELBIT, code)
        setup = struct.pack("HHHH80sI", BUS_VIRTUAL, 0x1, 0x1, 1,
                            b"capsnav smooth scroll", 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        self.notch_acc = 0

    def _event(self, etype, code, value):
        os.write(self.fd, struct.pack("llHHi", 0, 0, etype, code, value))

    def scroll(self, hires):
        """Send `hires` wheel units; a legacy notch accompanies every 120."""
        self._event(EV_REL, REL_WHEEL_HI_RES, hires)
        self.notch_acc += hires
        notches = int(self.notch_acc / NOTCH)  # truncates toward zero
        if notches:
            self.notch_acc -= notches * NOTCH
            self._event(EV_REL, REL_WHEEL, notches)
        self._event(EV_SYN, SYN_REPORT, 0)

    def close(self):
        fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        os.close(self.fd)


class Settings:
    """`key = value` settings from CONFIG_PATH, reloaded when the file changes."""

    def __init__(self):
        self.values = dict(DEFAULTS)
        self.mtime = None
        self.refresh()

    def refresh(self):
        try:
            mtime = os.stat(CONFIG_PATH).st_mtime
        except FileNotFoundError:
            mtime = None
        if mtime == self.mtime:
            return
        self.mtime = mtime
        values = dict(DEFAULTS)
        if mtime is not None:
            with open(CONFIG_PATH) as f:
                for n, line in enumerate(f, 1):
                    line = line.split("#", 1)[0].strip()
                    if not line:
                        continue
                    key, _, value = (s.strip() for s in line.partition("="))
                    try:
                        if key not in DEFAULTS:
                            raise ValueError(f"unknown setting {key!r}")
                        number = float(value)
                        if key == "speed" and number <= 0:
                            raise ValueError("must be greater than 0")
                        if number < 0:
                            raise ValueError("must be 0 or more")
                        values[key] = number
                    except ValueError as e:
                        print(f"{CONFIG_PATH}:{n}: {e}; ignoring",
                              file=sys.stderr, flush=True)
        self.values = values
        print(f"settings: {values}", file=sys.stderr, flush=True)

    @property
    def max_speed(self):
        return self.values["speed"] * NOTCH  # units/second

    @property
    def accel_tau(self):
        return self.values["ease_in_ms"] / 1000

    @property
    def decel_tau(self):
        return self.values["ease_out_ms"] / 1000


class Motion:
    """Velocity that eases toward the held direction's target speed."""

    def __init__(self, settings):
        self.settings = settings
        self.velocity = 0.0   # units/second, signed
        self.remainder = 0.0  # sub-unit carry so no motion is lost

    def step(self, direction, dt):
        target = direction * self.settings.max_speed
        tau = self.settings.accel_tau if direction else self.settings.decel_tau
        if tau == 0:
            self.velocity = target  # no easing: constant speed, instant stop
        else:
            self.velocity += (target - self.velocity) * (1 - math.exp(-dt / tau))
        if not direction and abs(self.velocity) < 20:
            self.velocity = 0.0
            self.remainder = 0.0
            return 0
        self.remainder += self.velocity * dt
        units = int(self.remainder)
        self.remainder -= units
        return units

    @property
    def moving(self):
        return self.velocity != 0.0


def run(wheel, settings):
    listen = subprocess.Popen(["keyd", "listen"], stdout=subprocess.PIPE,
                              bufsize=0)
    held = set()
    motion = Motion(settings)
    buf = b""
    last = time.monotonic()
    try:
        while True:
            timeout = 1 / TICK_HZ if (held or motion.moving) else None
            ready, _, _ = select.select([listen.stdout], [], [], timeout)
            if ready:
                chunk = os.read(listen.stdout.fileno(), 512)
                if not chunk:
                    return  # keyd went away; caller restarts us
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    line = line.decode(errors="replace").strip()
                    name = line[1:]
                    if name not in LAYER_DIRECTION:
                        continue
                    if line[0] == "+":
                        held.add(name)
                    elif line[0] == "-":
                        held.discard(name)
                if not motion.moving:
                    settings.refresh()  # pick up config edits between scrolls
                    last = time.monotonic()  # start fresh, no jump
            now = time.monotonic()
            dt, last = min(now - last, 0.05), now
            direction = sum(LAYER_DIRECTION[n] for n in held)
            units = motion.step(direction, dt)
            if units:
                wheel.scroll(units)
    finally:
        listen.kill()
        listen.wait()


def main():
    wheel = VirtualWheel()
    settings = Settings()
    try:
        while True:
            run(wheel, settings)
            time.sleep(1)  # keyd restarting; reconnect
    except KeyboardInterrupt:
        pass
    finally:
        wheel.close()


if __name__ == "__main__":
    sys.exit(main())
