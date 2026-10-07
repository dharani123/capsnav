#!/usr/bin/env python3
"""Live check against the running keyd: a reload must tell `keyd listen` that
mouse mode went off, or the top-bar icon stays filled after the Mappings
window saves (capsnav-indicator only knows what keyd listen reports).

Taps left Shift on a throwaway uinput keyboard (keyd grabs it, [ids] *), so
it needs root for /dev/uinput:  sudo python3 -I tests/keyd_reload_listen.py
Not part of the unittest suite: it reloads the installed keyd.
"""

import fcntl
import os
import queue
import struct
import subprocess
import sys
import threading
import time

EV_SYN, EV_KEY, SYN_REPORT = 0x00, 0x01, 0
KEY_LEFTSHIFT = 42
UI_SET_EVBIT, UI_SET_KEYBIT = 0x40045564, 0x40045565
UI_DEV_SETUP, UI_DEV_CREATE, UI_DEV_DESTROY = 0x405C5503, 0x5501, 0x5502


def keyboard():
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    for code in range(1, 256):  # keyd only grabs what looks like a keyboard
        fcntl.ioctl(fd, UI_SET_KEYBIT, code)
    fcntl.ioctl(fd, UI_DEV_SETUP, struct.pack(
        "HHHH80sI", 0x06, 0x1, 0x2, 1, b"capsnav reload test", 0))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    return fd


def key(fd, value):
    for etype, code, val in ((EV_KEY, KEY_LEFTSHIFT, value),
                             (EV_SYN, SYN_REPORT, 0)):
        os.write(fd, struct.pack("llHHi", 0, 0, etype, code, val))


class Listener:
    """`keyd listen` read on a thread, so no buffered line goes unseen."""

    def __init__(self):
        self.proc = subprocess.Popen(["keyd", "listen"],
                                     stdout=subprocess.PIPE, text=True)
        self.lines = queue.Queue()
        self.t0 = time.monotonic()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put((time.monotonic() - self.t0, line.strip()))

    def until(self, want, timeout=2):
        """Events up to and including `want`; (False, events) on timeout."""
        seen = []
        end = time.monotonic() + timeout
        while True:
            try:
                t, line = self.lines.get(timeout=max(0, end - time.monotonic()))
            except queue.Empty:
                return False, seen
            seen.append("%.3f %s" % (t, line))
            if line == want:
                return True, seen


def reload(listen):
    print("%.3f keyd reload" % (time.monotonic() - listen.t0))
    subprocess.run(["keyd", "reload"], check=True, capture_output=True)


def main():
    fd = keyboard()
    listen = Listener()
    try:
        reload(listen)  # start from a fresh keyd: mouse mode off
        time.sleep(1)  # let keyd grab the new device
        key(fd, 1)
        time.sleep(0.05)
        key(fd, 0)  # a tap (under overload_tap_timeout): mouse mode on
        ok, seen = listen.until("+mousemode")
        print("tap:", seen)
        if not ok:
            print("SETUP FAILED: no +mousemode after the tap")
            return 2
        time.sleep(0.3)  # let the tap's events in, then drop them
        while not listen.lines.empty():
            listen.lines.get()
        reload(listen)
        ok, seen = listen.until("-mousemode")
        print("PASS" if ok else "FAIL: keyd reset mouse mode but didn't say",
              seen)
        return 0 if ok else 1
    finally:
        listen.proc.kill()
        fcntl.ioctl(fd, UI_DEV_DESTROY)
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
