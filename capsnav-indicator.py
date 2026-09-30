#!/usr/bin/env python3
"""Mouse-mode indicator: a mouse icon in the top bar (next to Wi-Fi) while
mouse mode is on.

Started by capsnav-scroll --mouse, which writes "on" / "off" lines to its
stdin when mouse mode turns on or off. Uses AppIndicator (Ubuntu's
ubuntu-appindicators extension shows it); the icon is hidden while mouse mode
is off. Exits when stdin closes.
"""

import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

# Filled white mouse (icons/capsnav-mouse.svg, installed by install.sh);
# falls back to the theme's outline mouse if it's missing.
ICON_DIR = "/usr/local/share/capsnav/icons"
ICON = "capsnav-mouse"
if not os.path.exists(os.path.join(ICON_DIR, ICON + ".svg")):
    ICON = "input-mouse-symbolic"


def main():
    ind = AppIndicator.Indicator.new_with_path(
        "capsnav-mouse-mode", ICON,
        AppIndicator.IndicatorCategory.HARDWARE, ICON_DIR)
    ind.set_title("capsnav mouse mode")
    # AppIndicator requires a menu; it just names the mode.
    menu = Gtk.Menu()
    item = Gtk.MenuItem(label="Mouse mode on (tap left Shift to leave)")
    item.set_sensitive(False)
    menu.append(item)
    menu.show_all()
    ind.set_menu(menu)
    ind.set_status(AppIndicator.IndicatorStatus.PASSIVE)  # hidden

    def on_input(source, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            Gtk.main_quit()
            return False
        line = source.readline()
        if not line:
            Gtk.main_quit()
            return False
        cmd = line.strip()
        if cmd == "on":
            ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        elif cmd == "off":
            ind.set_status(AppIndicator.IndicatorStatus.PASSIVE)
        return True

    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                      on_input)
    Gtk.main()


if __name__ == "__main__":
    main()
