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
    "ease_in_ms": 100.0,   # time to reach ~90% of full speed after pressing
    "ease_out_ms": 200.0,  # time to lose ~90% of speed after releasing
    "tick_hz": 120.0,      # scroll events per second while moving
}
POSITIVE = {"speed", "tick_hz"}  # settings that must be > 0 (others >= 0)

# A critically damped spring reaches ~90% of its target at t = 3.89 / omega.
T90_FACTOR = 3.89

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
                        if key in POSITIVE and number <= 0:
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
    def ease_in(self):
        return self.values["ease_in_ms"] / 1000  # seconds

    @property
    def ease_out(self):
        return self.values["ease_out_ms"] / 1000  # seconds

    @property
    def period(self):
        return 1 / self.values["tick_hz"]  # seconds between scroll events


class Motion:
    """Scroll velocity driven toward the held direction's speed by a
    critically damped spring.

    Unlike a simple exponential ease, the spring keeps acceleration continuous
    too, so speed builds and fades along an S-curve with no kick at press or
    release. It never overshoots, and a new target mid-glide (release, or
    reversing j -> k) carries on from the current velocity and acceleration.
    """

    def __init__(self, settings):
        self.settings = settings
        self.velocity = 0.0   # units/second, signed
        self.accel = 0.0      # units/second^2
        self.remainder = 0.0  # sub-unit carry so no motion is lost

    def step(self, direction, dt):
        """Advance by dt seconds and return whole wheel units to send."""
        target = direction * self.settings.max_speed
        t90 = self.settings.ease_in if direction else self.settings.ease_out
        v0 = self.velocity
        if t90 == 0:
            self.velocity, self.accel = target, 0.0  # no easing: instant
        else:
            # Exact solution of x'' + 2w x' + w^2 x = 0 for x = v - target.
            w = T90_FACTOR / t90
            x0 = v0 - target
            c = self.accel + w * x0
            decay = math.exp(-w * dt)
            self.velocity = target + (x0 + c * dt) * decay
            self.accel = (self.accel - w * c * dt) * decay
        # End the glide before sub-unit steps round to a visible 1,0,1,0
        # flicker: below half a unit per event, it is simply over.
        stop_speed = 0.5 / dt
        if (not direction and abs(self.velocity) < stop_speed
                and abs(self.accel) < stop_speed / dt):
            self.velocity = self.accel = self.remainder = 0.0
            return 0
        self.remainder += (v0 + self.velocity) / 2 * dt  # trapezoid rule
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
    next_tick = None  # monotonic deadline of the next scroll event
    try:
        while True:
            if held or motion.moving:
                if next_tick is None:
                    next_tick = time.monotonic()  # respond to a press at once
                timeout = max(0.0, next_tick - time.monotonic())
            else:
                next_tick, timeout = None, None  # idle: sleep until a key
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
                continue  # key events only change `held`; ticks do the moving
            # Fixed deadlines (not "sleep one period") keep events evenly
            # spaced, and a fixed dt makes every step at a steady speed the
            # same size: uneven steps are what the eye sees as judder.
            period = settings.period
            direction = sum(LAYER_DIRECTION[n] for n in held)
            units = motion.step(direction, period)
            if units:
                wheel.scroll(units)
            now = time.monotonic()
            next_tick += period
            if now - next_tick > period:
                next_tick = now + period  # fell badly behind; resync
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
