#!/usr/bin/env python3
"""Smooth scrolling and pointer motion for the capsnav keyd layer.

keyd activates the empty layers `scrollup` / `scrolldown` while Caps+n / Caps+m
are held. This daemon watches those layer changes via `keyd listen` and emits a
stream of small scroll events from a virtual pointer, easing in on press and
gliding to a stop on release, so scrolling looks like a touchpad rather than
jumping one wheel notch at a time.

With --mouse it instead moves the pointer while Caps+i/j/k/l hold the
layers `ijklleft` / `ijklright` / … (and the `esdf…` ones), on the same spring
curve. It moves the pointer through XTest, which (unlike a virtual mouse)
bypasses pointer acceleration, so the curve arrives exactly. That needs the
user's X session, so --mouse runs as a user service, not as root.

Scroll events go out in one of two modes:
- continuous (preferred): a libinput quirk marks the device as a Lenovo
  ScrollPoint, so its REL_WHEEL values are treated as continuous scroll, like a
  touchpad. The X driver's ScrollPixelDistance makes CONTINUOUS_UNITS one click.
- wheel (fallback): high-resolution wheel events, 120 per click. libinput holds
  back the first half click of every scroll that starts after 500 ms of no
  scrolling, then releases it at once, a visible jerk in apps that don't
  animate scrolling (VS Code, terminals).
Continuous mode is used only once libinput has loaded the quirk; otherwise each
unit would scroll a whole click.

Speed and easing are read from CONFIG_PATH, which is re-read whenever it
changes, so edits take effect on the next scroll without a restart.

Scrolling must run as root (needs /dev/uinput and the keyd socket). --mouse
runs as the desktop user, who must be in the `keyd` group for the socket.
No dependencies beyond libX11/libXtst for --mouse.
"""

import ctypes
import ctypes.util
import fcntl
import math
import os
import re
import select
import struct
import subprocess
import sys
import threading
import time

# --- Tuning -----------------------------------------------------------------
CONFIG_PATH = "/etc/capsnav/mouse.conf"
# Defaults, used for any setting missing from CONFIG_PATH.
DEFAULTS = {
    "scroll_speed": 7.0,         # wheel clicks per second at full speed
    "scroll_ease_in_ms": 100.0,  # time to reach ~90% of full speed after pressing
    "pointer_speed": 1000.0,     # pointer pixels per second at full speed
    "pointer_ease_in_ms": 400.0, # like scroll_ease_in_ms; slower so short
                                 # taps nudge the pointer precisely
    "scroll_ease_out_ms": 200.0, # time to lose ~90% of speed after releasing
    "pointer_ease_out_ms": 120.0, # same for the pointer; short, since a click
                                  # during the glide turns into a drag
    "tick_hz": 120.0,            # events per second while moving
    "pointer_snap_margin_px": 40.0,  # how far inside the edge a snap lands
    "vsync": 1.0,                # scroll: 1 = one step per screen refresh
    "vsync_crtc": 0.0,           # which display pipe to follow (see mouse.conf)
}
# Settings that must be > 0 (others >= 0).
POSITIVE = {"scroll_speed", "pointer_speed", "tick_hz"}

# A critically damped spring reaches ~90% of its target at t = 3.89 / omega.
T90_FACTOR = 3.89

# Layer -> direction vector. Scroll: (wheel,), +1 = up. Mouse: (x, y) in
# screen pixels, +y = down.
SCROLL_LAYERS = {"scrolldown": (-1,), "scrollup": (1,)}
# While scrolling, holding Space (keyd layer "arrows") scrolls 6x as fast.
# Checked every tick, so pressing or releasing it mid-scroll changes speed at
# once (eased by the spring).
SCROLL_SPEED_LAYERS = {"arrows": 6.0}
# Pointer keys: two clusters, Caps+i/j/k/l and Caps+e/s/d/f, each turning on
# its own layers. Depending on the pointer mode (Caps+z cycles it), a cluster
# either moves the pointer smoothly or snaps it to that edge of its screen.
# Moving directions add up, so the same direction on both clusters moves
# twice as fast.
POINTER_LAYERS = {}
for _cluster in ("ijkl", "esdf"):
    for _side, _dir in (("left", (-1, 0)), ("right", (1, 0)),
                        ("up", (0, -1)), ("down", (0, 1))):
        POINTER_LAYERS[_cluster + _side] = (_cluster, _dir)
MOUSE_LAYERS = {name: d for name, (_, d) in POINTER_LAYERS.items()}
# (label, clusters that snap); Caps+z cycles through these.
POINTER_MODES = [("both move", set()),
                 ("e/s/d/f snap, i/j/k/l move", {"esdf"}),
                 ("i/j/k/l snap, e/s/d/f move", {"ijkl"})]
POINTER_MODE_PATH = os.path.expanduser("~/.config/capsnav/pointer-mode")
# capsnav-indicator shows an icon in the top bar, a filled mouse while mouse
# mode is on and a filled keyboard while off; the pointer helper starts it and feeds it
# "on" / "off", and "pointer <mode>" for its menu.
INDICATOR = None


def indicator(state):
    global INDICATOR
    try:
        if INDICATOR is None or INDICATOR.poll() is not None:
            INDICATOR = subprocess.Popen(["/usr/local/bin/capsnav-indicator"],
                                         stdin=subprocess.PIPE, text=True)
        INDICATOR.stdin.write(state + "\n")
        INDICATOR.stdin.flush()
    except OSError:
        INDICATOR = None


class PointerMode:
    """The current POINTER_MODES index, kept in POINTER_MODE_PATH so it
    survives restarts. Default: both move."""

    def __init__(self):
        try:
            with open(POINTER_MODE_PATH) as f:
                self.index = int(f.read().strip()) % len(POINTER_MODES)
        except (OSError, ValueError):
            self.index = 0

    @property
    def snapping(self):
        return POINTER_MODES[self.index][1]

    @property
    def label(self):
        return POINTER_MODES[self.index][0]

    def cycle(self):
        self.index = (self.index + 1) % len(POINTER_MODES)
        indicator("pointer " + self.label)
        try:
            os.makedirs(os.path.dirname(POINTER_MODE_PATH), exist_ok=True)
            with open(POINTER_MODE_PATH, "w") as f:
                f.write(f"{self.index}\n")
        except OSError:
            pass
        subprocess.Popen(["notify-send", "-t", "1500", "-h", "int:transient:1",
                          f"Pointer keys: {self.label}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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

DEVICE_NAME = "capsnav smooth scroll"
QUIRKS_PATH = "/etc/libinput/local-overrides.quirks"
WHEEL_UNITS = 120       # hi-res wheel units per click (fallback mode)
CONTINUOUS_UNITS = 50   # continuous units per click; must match the
                        # ScrollPixelDistance in 50-capsnav-scroll.conf


def xorg_start_times():
    """Start times (epoch seconds) of running Xorg servers."""
    with open("/proc/stat") as f:
        btime = next(int(l.split()[1]) for l in f if l.startswith("btime"))
    hz = os.sysconf("SC_CLK_TCK")
    times = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() != "Xorg":
                    continue
            with open(f"/proc/{pid}/stat") as f:
                # Field 22 is the start time; split after the ")" of comm.
                fields = f.read().rsplit(")", 1)[1].split()
            times.append(btime + int(fields[19]) / hz)
        except (FileNotFoundError, ProcessLookupError, IndexError):
            continue
    return times


def continuous_mode_ready():
    """True if libinput has (or will have) loaded our ScrollPoint quirk.

    libinput reads quirks once, when the display server starts, so the quirk
    is live only if every running Xorg started after the file was written.
    """
    try:
        with open(QUIRKS_PATH) as f:
            if f"MatchName={DEVICE_NAME}" not in f.read():
                return False
        quirk_mtime = os.stat(QUIRKS_PATH).st_mtime
    except FileNotFoundError:
        return False
    return all(start > quirk_mtime for start in xorg_start_times())


class VirtualWheel:
    def __init__(self, continuous):
        self.continuous = continuous
        self.units_per_click = CONTINUOUS_UNITS if continuous else WHEEL_UNITS
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        # libinput only treats a device as a pointer if it has REL_X/REL_Y
        # and a button, so declare them even though they're never sent.
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_KEYBIT, BTN_LEFT)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
        # Without REL_WHEEL_HI_RES, libinput flushes every event at once;
        # the quirk then turns our REL_WHEEL values into continuous scroll.
        codes = [REL_X, REL_Y, REL_WHEEL]
        if not continuous:
            codes.append(REL_WHEEL_HI_RES)
        for code in codes:
            fcntl.ioctl(self.fd, UI_SET_RELBIT, code)
        setup = struct.pack("HHHH80sI", BUS_VIRTUAL, 0x1, 0x1, 1,
                            DEVICE_NAME.encode(), 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        self.notch_acc = 0

    def _event(self, etype, code, value):
        os.write(self.fd, struct.pack("llHHi", 0, 0, etype, code, value))

    def scroll(self, units):
        """Send `units` (see units_per_click) of scroll."""
        if self.continuous:
            self._event(EV_REL, REL_WHEEL, units)
        else:
            # Hi-res units; a legacy notch accompanies every 120.
            self._event(EV_REL, REL_WHEEL_HI_RES, units)
            self.notch_acc += units
            notches = int(self.notch_acc / WHEEL_UNITS)  # toward zero
            if notches:
                self.notch_acc -= notches * WHEEL_UNITS
                self._event(EV_REL, REL_WHEEL, notches)
        self._event(EV_SYN, SYN_REPORT, 0)

    def send(self, units):
        self.scroll(units[0])

    def close(self):
        fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        os.close(self.fd)


class XTestPointer:
    """Moves the X pointer by exact pixels via XTest (no acceleration)."""

    def __init__(self):
        self.x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self.xtst = ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XFlush.argtypes = [ctypes.c_void_p]
        self.x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.xtst.XTestFakeRelativeMotionEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.xtst.XTestFakeMotionEvent.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_ulong]
        self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x11.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong] + [
            ctypes.c_void_p] * 7
        self.display = self.x11.XOpenDisplay(None)  # uses $DISPLAY
        if not self.display:
            raise SystemExit("cannot open X display (is DISPLAY set?)")

    def send(self, units):
        dx, dy = units
        self.xtst.XTestFakeRelativeMotionEvent(self.display, dx, dy, 0)
        self.x11.XFlush(self.display)

    def _query(self):
        """Pointer (root x, root y, button mask)."""
        root = self.x11.XDefaultRootWindow(self.display)
        win = ctypes.c_ulong()
        xs = [ctypes.c_int() for _ in range(4)]
        mask = ctypes.c_uint()
        self.x11.XQueryPointer(self.display, root, ctypes.byref(win),
                               ctypes.byref(win), *map(ctypes.byref, xs),
                               ctypes.byref(mask))
        return xs[0].value, xs[1].value, mask.value

    def button_down(self):
        """True while any mouse button (left, middle, right) is pressed."""
        return bool(self._query()[2] & (0b111 << 8))  # Button1..3Mask

    def snap(self, direction, margin):
        """Jump to `margin` px inside the edge of the pointer's monitor in
        `direction` (dx, dy), keeping the other coordinate."""
        x, y, _ = self._query()
        out = subprocess.run(["xrandr", "--listmonitors"], capture_output=True,
                             text=True).stdout
        for w, h, mx, my in re.findall(r"(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)", out):
            w, h, mx, my = map(int, (w, h, mx, my))
            if mx <= x < mx + w and my <= y < my + h:
                break
        else:
            return
        dx, dy = direction
        if dx:
            x = mx + margin if dx < 0 else mx + w - 1 - margin
        if dy:
            y = my + margin if dy < 0 else my + h - 1 - margin
        self.xtst.XTestFakeMotionEvent(self.display, -1, int(x), int(y), 0)
        self.x11.XFlush(self.display)

    def close(self):
        self.x11.XCloseDisplay(self.display)


class VBlank(threading.Thread):
    """Wakes the scroll loop once per refresh of one screen, via the DRM
    WAIT_VBLANK ioctl on /dev/dri/card*. While `active` is set it writes a
    byte to `self.r` after every vblank; `period` tracks the measured frame
    interval. If waiting fails (screen off, bad pipe) it falls back to a timer
    so scrolling keeps working."""

    IOCTL = 0xC018643A  # _IOWR('d', 0x3a, union drm_wait_vblank), 24 bytes

    def __init__(self, settings):
        super().__init__(daemon=True)
        self.settings = settings
        self.fd = None
        for card in sorted(p for p in os.listdir("/dev/dri") if p.startswith("card")):
            try:
                fd = os.open(f"/dev/dri/{card}", os.O_RDWR)
                self.fd, self.card = fd, card
                self._wait(int(settings.values["vsync_crtc"]))
                break
            except OSError:
                if self.fd is not None:
                    os.close(self.fd)
                self.fd = None
        if self.fd is None:
            raise OSError("no /dev/dri/card* supports vblank waits")
        self.r, self._w = os.pipe()
        os.set_blocking(self.r, False)
        self.active = threading.Event()
        self.period = settings.period

    def _wait(self, crtc):
        kind = 0x1  # _DRM_VBLANK_RELATIVE: the next vblank
        if crtc == 1:
            kind |= 0x20000000  # _DRM_VBLANK_SECONDARY
        elif crtc > 1:
            kind |= (crtc << 1) & 0x3E  # _DRM_VBLANK_HIGH_CRTC
        buf = bytearray(struct.pack("IIqq", kind, 1, 0, 0))
        fcntl.ioctl(self.fd, self.IOCTL, buf, True)
        _, seq, sec, usec = struct.unpack("IIqq", buf)
        return seq, sec + usec / 1e6

    def run(self):
        last = None  # (sequence, timestamp) of the previous vblank
        while True:
            self.active.wait()
            try:
                seq, stamp = self._wait(int(self.settings.values["vsync_crtc"]))
                if last and seq == last[0] + 1:
                    # Smooth the measured interval; steps use it as dt, so
                    # each frame moves the same distance.
                    self.period += 0.1 * (stamp - last[1] - self.period)
                last = (seq, stamp)
            except OSError:
                last = None
                time.sleep(self.settings.period)
            os.write(self._w, b"v")


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
    def speed(self):
        return self.values["scroll_speed"]  # clicks/second

    @property
    def ease_in(self):
        return self.values["scroll_ease_in_ms"] / 1000  # seconds

    @property
    def ease_out(self):
        return self.values["scroll_ease_out_ms"] / 1000  # seconds

    @property
    def period(self):
        return 1 / self.values["tick_hz"]  # seconds between scroll events


class Motion:
    """Scroll velocity driven toward the held direction's speed by a
    critically damped spring.

    Unlike a simple exponential ease, the spring keeps acceleration continuous
    too, so speed builds and fades along an S-curve with no kick at press or
    release. It never overshoots, and a new target mid-glide (release, or
    reversing n -> m) carries on from the current velocity and acceleration.
    """

    def __init__(self, settings, units_per_click, speed_key="scroll_speed",
                 ease_in_key="scroll_ease_in_ms",
                 ease_out_key="scroll_ease_out_ms"):
        self.settings = settings
        self.units_per_click = units_per_click
        self.speed_key = speed_key  # setting giving full speed, per unit above
        self.ease_in_key = ease_in_key
        self.ease_out_key = ease_out_key
        self.velocity = 0.0   # units/second, signed
        self.accel = 0.0      # units/second^2
        self.remainder = 0.0  # sub-unit carry so no motion is lost

    def step(self, direction, dt, whole_steps=False):
        """Advance by dt seconds and return whole wheel units to send.
        With `whole_steps`, the full speed is rounded to a whole number of
        units per step, so a steady scroll moves every frame by exactly the
        same amount (e.g. 5.01 units/frame would add a 6 every ~100 frames)."""
        target = (direction * self.settings.values[self.speed_key]
                  * self.units_per_click)
        if whole_steps and target:
            target = max(1, round(abs(target) * dt)) / dt * (1 if target > 0 else -1)
        if direction:
            t90 = self.settings.values[self.ease_in_key] / 1000
        else:
            t90 = self.settings.values[self.ease_out_key] / 1000
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


def run(output, layers, motions, settings, vblank=None):
    """Follow `layers` via keyd listen, easing each axis of `motions` toward
    the held direction and sending whole units to `output` every tick. With
    `vblank` (and the vsync setting on), ticks come from screen refreshes
    instead of a timer."""
    listen = subprocess.Popen(["keyd", "listen"], stdout=subprocess.PIPE,
                              bufsize=0)
    held = set()
    pointer = isinstance(output, XTestPointer)
    mode = PointerMode() if pointer else None
    if pointer:
        # Show the (keyboard) icon from the start; keyd listen then reports
        # mouse mode if it's already on.
        indicator("off")
        indicator("pointer " + mode.label)
    modifiers = set()  # active SCROLL_SPEED_LAYERS (scrolling only)
    buf = b""
    next_tick = None  # monotonic deadline of the next scroll event
    try:
        while True:
            moving = any(m.moving for m in motions)
            synced = vblank is not None and settings.values["vsync"]
            fds = [listen.stdout]
            if synced:
                # One step per screen refresh: every frame moves the same
                # amount, instead of a timer drifting against the display.
                timeout = None
                if held or moving:
                    vblank.active.set()
                    fds.append(vblank.r)
                else:
                    vblank.active.clear()
            elif held or moving:
                if next_tick is None:
                    next_tick = time.monotonic()  # respond to a press at once
                timeout = max(0.0, next_tick - time.monotonic())
            else:
                next_tick, timeout = None, None  # idle: sleep until a key
            ready, _, _ = select.select(fds, [], [], timeout)
            if listen.stdout in ready:
                chunk = os.read(listen.stdout.fileno(), 512)
                if not chunk:
                    return  # keyd went away; caller restarts us
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    line = line.decode(errors="replace").strip()
                    name = line[1:]
                    if pointer and name == "mousemode":
                        # A Caps tap toggled mouse mode: say so, since keys now
                        # move the pointer instead of typing.
                        indicator("on" if line[0] == "+" else "off")
                        continue
                    if pointer and name == "pointermode":
                        if line[0] == "+":
                            mode.cycle()
                        continue
                    if (pointer and name in POINTER_LAYERS
                            and POINTER_LAYERS[name][0] in mode.snapping):
                        if line[0] == "+":
                            output.snap(POINTER_LAYERS[name][1], settings.values[
                                "pointer_snap_margin_px"])
                            for m in motions:  # drop any glide
                                m.velocity = m.accel = m.remainder = 0.0
                        held.discard(name)
                        continue
                    if name in SCROLL_SPEED_LAYERS and layers is SCROLL_LAYERS:
                        if line[0] == "+":
                            modifiers.add(name)
                        else:
                            modifiers.discard(name)
                        continue
                    if name not in layers:
                        continue
                    if line[0] == "+":
                        held.add(name)
                    elif line[0] == "-":
                        held.discard(name)
                if not any(m.moving for m in motions):
                    settings.refresh()  # pick up config edits between scrolls
                continue  # key events only change `held`; ticks do the moving
            # Fixed deadlines (not "sleep one period") keep events evenly
            # spaced, and a fixed dt makes every step at a steady speed the
            # same size: uneven steps are what the eye sees as judder.
            if synced:
                try:
                    os.read(vblank.r, 64)  # consume this refresh's wakeup(s)
                except BlockingIOError:
                    pass
                period = vblank.period
            else:
                period = settings.period
            # Pointer: a click during the glide after release would drag the
            # clicked thing along the rest of the glide, so stop dead instead.
            if (not held and hasattr(output, "button_down")
                    and output.button_down()):
                for m in motions:
                    m.velocity = m.accel = m.remainder = 0.0
                continue
            factor = 1.0
            for name in modifiers:
                factor *= SCROLL_SPEED_LAYERS[name]
            units = [m.step(sum(layers[n][axis] for n in held) * factor,
                            period, whole_steps=synced)
                     for axis, m in enumerate(motions)]
            if any(units):
                output.send(units)
            if synced:
                continue
            now = time.monotonic()
            next_tick += period
            if now - next_tick > period:
                next_tick = now + period  # fell badly behind; resync
    finally:
        listen.kill()
        listen.wait()


def main():
    settings = Settings()
    if "--mouse" in sys.argv[1:]:
        output = XTestPointer()
        layers = MOUSE_LAYERS
        motions = [Motion(settings, 1, "pointer_speed", "pointer_ease_in_ms",
                          "pointer_ease_out_ms")
                   for _ in range(2)]
    else:
        continuous = continuous_mode_ready()
        print(f"scroll mode: {'continuous' if continuous else 'wheel'}",
              file=sys.stderr, flush=True)
        output = VirtualWheel(continuous)
        layers = SCROLL_LAYERS
        motions = [Motion(settings, output.units_per_click)]
    vblank = None
    if "--mouse" not in sys.argv[1:]:
        try:
            vblank = VBlank(settings)
            vblank.start()
            print(f"vsync: available via /dev/dri/{vblank.card}",
                  file=sys.stderr, flush=True)
        except OSError as e:
            print(f"vsync: unavailable ({e}); using tick_hz", file=sys.stderr,
                  flush=True)
    try:
        while True:
            run(output, layers, motions, settings, vblank)
            time.sleep(1)  # keyd restarting (or no socket access); retry
    except KeyboardInterrupt:
        pass
    finally:
        output.close()


if __name__ == "__main__":
    sys.exit(main())
