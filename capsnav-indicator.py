#!/usr/bin/env python3
"""Mouse-mode indicator: an icon in the top bar (next to Wi-Fi), a filled
mouse while mouse mode is on and a filled keyboard while it's off.

Started by capsnav-scroll --mouse, which writes "off" at startup and then
"on" / "off" lines to its stdin when mouse mode turns on or off, and
"pointer <mode>" lines with the Caps+z pointer mode. Uses AppIndicator
(Ubuntu's ubuntu-appindicators extension shows it). Its menu names both
modes and opens the mappings window. Exits when stdin closes.
"""

import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

# Filled white mouse (on) / keyboard (off) (icons/, installed by install.sh
# into the hicolor icon theme); falls back to the theme's mouse and keyboard
# icons if they're missing.
# They must be found by name in the icon theme, not through an icon theme path
# on the indicator: Ubuntu's AppIndicator extension (v58) never clears its
# "still loading" mark for an icon loaded from such a path, so once the icon
# cache drops the unused icon (~2 min), switching back to it is ignored and
# the top-bar icon sticks while the menu text changes.
ICON_DIR = "/usr/local/share/icons/hicolor/scalable/status"
ICON_ON, ICON_OFF = "capsnav-mouse", "capsnav-keyboard"
if not os.path.exists(os.path.join(ICON_DIR, ICON_OFF + ".svg")):
    ICON_ON, ICON_OFF = "input-mouse-symbolic", "input-keyboard-symbolic"
LABEL_ON = "Mouse mode on (tap left Shift to leave)"
LABEL_OFF = "Mouse mode off (tap left Shift to turn on)"
POINTER_LABEL = "Pointer keys: %s (Caps+z to change)"


def main():
    ind = AppIndicator.Indicator.new(
        "capsnav-mouse-mode", ICON_OFF,
        AppIndicator.IndicatorCategory.HARDWARE)
    ind.set_title("capsnav mouse mode")
    # The menu names both modes and opens the mappings window.
    menu = Gtk.Menu()
    item = Gtk.MenuItem(label=LABEL_OFF)
    item.set_sensitive(False)
    menu.append(item)
    pointer = Gtk.MenuItem(label=POINTER_LABEL % "…")
    pointer.set_sensitive(False)
    menu.append(pointer)
    mappings = Gtk.MenuItem(label="Mappings…")
    mappings.connect("activate",
                     lambda _i: subprocess.Popen(["capsnav-mappings"]))
    menu.append(mappings)
    menu.show_all()
    ind.set_menu(menu)
    ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)  # always shown

    # Read the raw fd, not sys.stdin: its buffered readline() can pull two
    # lines ("off" then "on" at startup) into Python's buffer but return one,
    # and the watch never fires for the line left behind, so the icon would
    # stay a step behind. Handle every complete line each time instead.
    fd = sys.stdin.fileno()
    pending = b""

    def on_input(_source, condition):
        nonlocal pending
        chunk = os.read(fd, 4096) if condition & GLib.IO_IN else b""
        if not chunk:
            Gtk.main_quit()  # the helper went away
            return False
        *lines, pending = (pending + chunk).split(b"\n")
        for line in lines:
            cmd = line.decode(errors="replace").strip()
            if cmd in ("on", "off"):
                on = cmd == "on"
                ind.set_icon_full(ICON_ON if on else ICON_OFF,
                                  "Mouse mode " + cmd)
                item.set_label(LABEL_ON if on else LABEL_OFF)
            elif cmd.startswith("pointer "):
                pointer.set_label(POINTER_LABEL % cmd[len("pointer "):])
        return True

    GLib.io_add_watch(fd, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, on_input)
    Gtk.main()


if __name__ == "__main__":
    main()
