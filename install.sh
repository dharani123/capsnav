#!/usr/bin/env bash
# Build/install keyd from keyd-src, apply the capsnav config, and install the
# smooth-scroll helper and the switch-monitor shortcut.
set -e
cd "$(dirname "$0")"
make -C keyd-src
sudo make -C keyd-src install
sudo cp default.conf /etc/keyd/default.conf
sudo systemctl enable --now keyd
sudo keyd reload
sudo install -Dm644 scroll.conf /etc/capsnav/scroll.conf
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

# Caps+p sends Super+Alt+O; bind that to capsnav-switch-monitor in GNOME.
# Runs as you, not root: GNOME shortcuts are per-user settings.
sudo install -m755 capsnav-switch-monitor.sh /usr/local/bin/capsnav-switch-monitor
schema=org.gnome.settings-daemon.plugins.media-keys
if gsettings list-schemas 2>/dev/null | grep -qx "$schema"; then
	base=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
	list=$(gsettings get $schema custom-keybindings)
	path=
	# Reuse an existing entry for this script, so reinstalling doesn't duplicate it.
	for p in $(echo "$list" | grep -o "'[^']*'" | tr -d "'"); do
		if gsettings get $schema.custom-keybinding:"$p" command | grep -q switch-monitor; then
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
	gsettings set $schema.custom-keybinding:"$path" name 'capsnav: switch monitor'
	gsettings set $schema.custom-keybinding:"$path" command /usr/local/bin/capsnav-switch-monitor
	gsettings set $schema.custom-keybinding:"$path" binding '<Super><Alt>o'
else
	echo "GNOME not found: bind Super+Alt+O to /usr/local/bin/capsnav-switch-monitor yourself for Caps+p."
fi
if ! command -v xdotool >/dev/null; then
	echo "Caps+p needs xdotool: sudo apt install xdotool"
fi

sleep 1
if sudo journalctl -u capsnav-scroll -n 50 -o cat | grep "scroll mode" | tail -1 | grep -q wheel; then
	echo
	echo "Reboot once to finish smooth-scroll setup (libinput loads its settings at login)."
fi
