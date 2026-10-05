#!/usr/bin/env bash
# Install everything capsnav needs: system packages, keyd (built from
# keyd-src) and its config, the smooth-scroll and pointer-motion helper, the Caps+p
# switch-monitor script, and its GNOME shortcut.
# Run as your normal user; it uses sudo where needed. Safe to re-run.
set -e
cd "$(dirname "$0")"
need_reboot=

# System packages: build tools, python3, xdotool/xprop/xrandr (Caps+p).
if command -v apt-get >/dev/null; then
	# A broken third-party repo shouldn't stop the install.
	sudo apt-get update || true
	sudo apt-get install -y git build-essential python3 \
		xdotool x11-utils x11-xserver-utils \
		python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 python3-xlib
elif command -v dnf >/dev/null; then
	sudo dnf install -y git gcc make python3 xdotool xprop xrandr \
		python3-gobject gtk3 libayatana-appindicator-gtk3 python3-xlib
else
	echo "No apt-get or dnf: install the packages listed in README.md yourself."
fi

make -C keyd-src
sudo make -C keyd-src install
sudo cp capsnav-nav /etc/keyd/capsnav-nav  # included by default.conf
sudo cp default.conf /etc/keyd/default.conf
sudo install -Dm644 system/keyd-restart.conf /etc/systemd/system/keyd.service.d/capsnav-restart.conf
sudo systemctl daemon-reload
sudo systemctl enable --now keyd
sudo keyd reload
sudo install -Dm644 mouse.conf /etc/capsnav/mouse.conf
sudo rm -f /etc/capsnav/scroll.conf  # old name, before mouse.conf
# libinput quirk + X setting for continuous scrolling (see capsnav-scroll.py).
# local-overrides.quirks is a single shared file, so append rather than replace.
quirks=/etc/libinput/local-overrides.quirks
if ! sudo grep -qs "MatchName=capsnav smooth scroll" "$quirks"; then
	sudo mkdir -p /etc/libinput
	{ echo; cat system/capsnav.quirks; } | sudo tee -a "$quirks" >/dev/null
fi
if [ -d /etc/X11 ]; then
	sudo install -Dm644 system/50-capsnav-scroll.conf /etc/X11/xorg.conf.d/50-capsnav-scroll.conf
fi
sudo install -m755 capsnav-scroll.py /usr/local/bin/capsnav-scroll
sudo install -m644 capsnav-scroll.service /etc/systemd/system/capsnav-scroll.service
sudo systemctl daemon-reload
sudo systemctl enable capsnav-scroll
sudo systemctl restart capsnav-scroll
# Pointer motion (Caps+i/j/k/l): same program as a user service, since
# XTest needs your X session. The keyd group lets it read `keyd listen`.
if ! id -nG "$USER" | grep -qw keyd; then
	sudo usermod -aG keyd "$USER"
	need_reboot=1
fi
install -Dm644 capsnav-mouse.service "$HOME/.config/systemd/user/capsnav-mouse.service"
# Per-app overrides (app.conf, e.g. VS Code code navigation) via keyd's
# application mapper, run as a user service.
install -Dm644 app.conf "$HOME/.config/keyd/app.conf"
install -Dm644 capsnav-appmap.service "$HOME/.config/systemd/user/capsnav-appmap.service"
systemctl --user daemon-reload
systemctl --user enable capsnav-mouse
systemctl --user restart capsnav-mouse
systemctl --user enable capsnav-appmap
systemctl --user restart capsnav-appmap

sudo install -m755 capsnav-switch-monitor.sh /usr/local/bin/capsnav-switch-monitor
# Pointer follows keyboard focus (user service: needs the X session).
sudo install -m755 capsnav-focus-follow.sh /usr/local/bin/capsnav-focus-follow
install -Dm644 capsnav-focus-follow.service "$HOME/.config/systemd/user/capsnav-focus-follow.service"
systemctl --user daemon-reload
systemctl --user enable capsnav-focus-follow
systemctl --user restart capsnav-focus-follow
# Top-bar mouse icon while mouse mode is on (AppIndicator, GTK 3).
sudo install -m755 capsnav-indicator.py /usr/local/bin/capsnav-indicator
sudo install -Dm644 icons/capsnav-mouse.svg /usr/local/share/capsnav/icons/capsnav-mouse.svg

# GNOME custom shortcuts for Caps keys that run a program: keyd (root, no X
# access) sends a key combo, and GNOME runs the command. Runs as you, not root:
# shortcuts are per-user settings.
schema=org.gnome.settings-daemon.plugins.media-keys
base=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
gnome_shortcut() { # name command binding
	local list path= p i
	list=$(gsettings get $schema custom-keybindings)
	# Reuse the entry with this name, so reinstalling doesn't duplicate it.
	for p in $(echo "$list" | grep -o "'[^']*'" | tr -d "'"); do
		if [ "$(gsettings get $schema.custom-keybinding:"$p" name)" = "'$1'" ]; then
			path=$p
		fi
	done
	if [ -z "$path" ]; then
		i=0
		while echo "$list" | grep -q "$base/custom$i/"; do i=$((i + 1)); done
		path=$base/custom$i/
		if [ "$list" = "@as []" ]; then list="['$path']"; else list="${list%]}, '$path']"; fi
		gsettings set $schema custom-keybindings "$list"
	fi
	gsettings set $schema.custom-keybinding:"$path" name "$1"
	gsettings set $schema.custom-keybinding:"$path" command "$2"
	gsettings set $schema.custom-keybinding:"$path" binding "$3"
}

if gsettings list-schemas 2>/dev/null | grep -qx "$schema"; then
	# Caps+p sends Super+Alt+O, Caps+u sends Super+Alt+U.
	gnome_shortcut 'capsnav: switch monitor' /usr/local/bin/capsnav-switch-monitor '<Super><Alt>o'
	gnome_shortcut 'capsnav: center pointer' '/usr/local/bin/capsnav-switch-monitor --center' '<Super><Alt>u'
else
	echo "GNOME not found: bind Super+Alt+O to /usr/local/bin/capsnav-switch-monitor"
	echo "and Super+Alt+U to 'capsnav-switch-monitor --center' yourself for Caps+p/u."
fi

sleep 1
if ! systemctl is-active --quiet keyd; then
	echo "keyd is not running: check 'journalctl -u keyd -b' and run 'sudo systemctl restart keyd'."
fi
if sudo journalctl -u capsnav-scroll -n 50 -o cat | grep "scroll mode" | tail -1 | grep -q wheel; then
	need_reboot=1
fi
echo
echo "Run ./check.sh any time to verify the setup (share its output when asking for help)."
if [ -n "$need_reboot" ]; then
	echo "Done. Reboot once to finish (smooth scroll and the keyd group load at login)."
else
	echo "Done."
fi
