#!/usr/bin/env bash
# Switch to the next workspace, wrapping from the last back to the first (with
# two workspaces, a toggle). X11 only. Caps+x sends Super+Alt+X, which
# install.sh binds to this script as a GNOME custom shortcut.
cur=$(xdotool get_desktop) n=$(xdotool get_num_desktops)
xdotool set_desktop $(((cur + 1) % n))
