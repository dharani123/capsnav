#!/usr/bin/env python3
"""Preview how capsnav smooth-scroll settings feel, without root.

Simulates holding Caps+n for a while and releasing, using the same Motion code
as the daemon, then draws the speed curve and prints the numbers that matter.

    tools/scroll-curve.py                  # settings from ../mouse.conf
    tools/scroll-curve.py 100/200 70/150   # compare ease_in/ease_out presets
    tools/scroll-curve.py --hold 0.4 --hz 60 100/200
"""

import argparse
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("capsnav_scroll",
                                               REPO / "capsnav-scroll.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

WIDTH, HEIGHT = 64, 10


class FixedSettings(cs.Settings):
    """Settings from a preset instead of the live config file."""

    def __init__(self, values):
        self.values = values
        self.mtime = None

    def refresh(self):
        pass


def load_conf(path):
    cs.CONFIG_PATH = str(path)
    import contextlib, io
    with contextlib.redirect_stderr(io.StringIO()):
        return dict(cs.Settings().values)


def simulate(values, hold):
    """Speed (as a fraction of full speed) and units sent, per tick."""
    motion = cs.Motion(FixedSettings(values), cs.CONTINUOUS_UNITS)
    period = 1 / values["tick_hz"]
    full = values["scroll_speed"] * cs.CONTINUOUS_UNITS
    speeds, units, t = [], [], 0.0
    while True:
        direction = 1 if t < hold else 0
        units.append(motion.step(direction, period))
        speeds.append(motion.velocity / full)
        t += period
        if t >= hold and not motion.moving:
            return speeds, units, period
        if t > hold + 5:
            raise RuntimeError("did not stop within 5 s of release")


def first_time(speeds, period, pred, start=0):
    for i in range(start, len(speeds)):
        if pred(speeds[i]):
            return (i + 1) * period
    return None


def ms(seconds):
    return "-" if seconds is None else f"{seconds * 1000:.0f} ms"


def plot(speeds, period, hold):
    cols = []
    duration = len(speeds) * period
    for c in range(WIDTH):
        i = min(int(c / WIDTH * len(speeds)), len(speeds) - 1)
        cols.append(speeds[i])
    release_col = int(hold / duration * WIDTH)
    rows = []
    for r in range(HEIGHT, 0, -1):
        level = r / HEIGHT
        line = "".join("#" if s >= level - 0.5 / HEIGHT else
                       ("|" if c == release_col else " ")
                       for c, s in enumerate(cols))
        label = "full |" if r == HEIGHT else "     |"
        rows.append(label + line)
    rows.append("     +" + "-" * WIDTH)
    rows.append("      0" + " " * (release_col - 1) + "^ release"
                + f"   ({duration * 1000:.0f} ms total)")
    return "\n".join(rows)


def report(name, values, hold):
    speeds, units, period = simulate(values, hold)
    release = int(round(hold / period))
    t50 = first_time(speeds, period, lambda s: s >= 0.5)
    t90 = first_time(speeds, period, lambda s: s >= 0.9)
    stop = len(speeds) * period - hold
    glide = sum(units[release:]) / cs.CONTINUOUS_UNITS
    tap_speeds, tap_units, _ = simulate(values, 0.06)
    overshoot = max(speeds) > 1.0001 or min(speeds) < -1e-9
    steady = [u for u, s in zip(units, speeds) if s > 0.999]
    print(f"== {name}: ease_in {values['scroll_ease_in_ms']:g} ms, "
          f"ease_out {values['ease_out_ms']:g} ms, speed "
          f"{values['scroll_speed']:g} clicks/s, {values['tick_hz']:g} Hz")
    print(plot(speeds, period, hold))
    print(f"  half speed after      {ms(t50)}")
    print(f"  90% speed after       {ms(t90)}")
    print(f"  stops after release   {ms(stop)}  (glides {glide:.2f} clicks)")
    print(f"  60 ms tap moves       {sum(tap_units) / cs.CONTINUOUS_UNITS:.2f} clicks")
    if steady:
        print(f"  steady step sizes     {sorted(set(steady))} units/event")
    print(f"  overshoot             {'YES' if overshoot else 'none'}")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("presets", nargs="*", metavar="IN/OUT",
                    help="scroll_ease_in_ms/ease_out_ms pairs, e.g. 100/200")
    ap.add_argument("--hold", type=float, default=0.6,
                    help="seconds to hold the key (default 0.6)")
    ap.add_argument("--hz", type=float, help="override tick_hz")
    ap.add_argument("--speed", type=float, help="override scroll_speed")
    ap.add_argument("--conf", default=REPO / "mouse.conf",
                    help="base settings file (default ../mouse.conf)")
    args = ap.parse_args()

    base = load_conf(args.conf)
    if args.hz:
        base["tick_hz"] = args.hz
    if args.speed:
        base["scroll_speed"] = args.speed

    if not args.presets:
        report("mouse.conf", base, args.hold)
    for p in args.presets:
        ease_in, _, ease_out = p.partition("/")
        values = dict(base, scroll_ease_in_ms=float(ease_in),
                      ease_out_ms=float(ease_out or ease_in))
        report(p, values, args.hold)


if __name__ == "__main__":
    main()
