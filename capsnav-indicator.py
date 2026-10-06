#!/usr/bin/env python3
"""Mouse-mode indicator: a mouse icon in the top bar (next to Wi-Fi), filled
while mouse mode is on and outlined while it's off.

Started by capsnav-scroll --mouse, which writes "off" at startup and then
"on" / "off" lines to its stdin when mouse mode turns on or off. Uses
AppIndicator (Ubuntu's ubuntu-appindicators extension shows it). Its menu
names the mode and opens the mappings window. Exits when stdin closes.
"""

import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

# Filled / outlined white mouse (icons/, installed by install.sh); falls back
# to the theme's mouse icon if they're missing.
ICON_DIR = "/usr/local/share/capsnav/icons"
ICON_ON, ICON_OFF = "capsnav-mouse", "capsnav-mouse-off"
if not os.path.exists(os.path.join(ICON_DIR, ICON_ON + ".svg")):
    ICON_ON = ICON_OFF = "input-mouse-symbolic"
LABEL_ON = "Mouse mode on (tap left Shift to leave)"
LABEL_OFF = "Mouse mode off (tap left Shift to turn on)"


def main():
    ind = AppIndicator.Indicator.new_with_path(
        "capsnav-mouse-mode", ICON_OFF,
        AppIndicator.IndicatorCategory.HARDWARE, ICON_DIR)
    ind.set_title("capsnav mouse mode")
    # The menu names the mode and opens the mappings window.
    menu = Gtk.Menu()
    item = Gtk.MenuItem(label=LABEL_OFF)
    item.set_sensitive(False)
    menu.append(item)
    mappings = Gtk.MenuItem(label="Mappings…")
    mappings.connect("activate",
                     lambda _i: subprocess.Popen(["capsnav-mappings"]))
    menu.append(mappings)
    menu.show_all()
    ind.set_menu(menu)
    ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)  # always shown

    def on_input(source, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            Gtk.main_quit()
            return False
        line = source.readline()
        if not line:
            Gtk.main_quit()
            return False
        cmd = line.strip()
        if cmd in ("on", "off"):
            on = cmd == "on"
            ind.set_icon_full(ICON_ON if on else ICON_OFF,
                              "Mouse mode " + cmd)
            item.set_label(LABEL_ON if on else LABEL_OFF)
        return True

    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                      on_input)
    Gtk.main()


if __name__ == "__main__":
    main()
