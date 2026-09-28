#!/usr/bin/env bash
# Build/install keyd from keyd-src, apply the capsnav config, and install the
# smooth-scroll helper and the Caps+p / Caps+f shortcuts.
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

sudo install -m755 capsnav-switch-monitor.sh /usr/local/bin/capsnav-switch-monitor
if gsettings list-schemas 2>/dev/null | grep -qx "$schema"; then
	# Caps+p sends Super+Alt+O
	gnome_shortcut 'capsnav: switch monitor' /usr/local/bin/capsnav-switch-monitor '<Super><Alt>o'
	# Caps+f sends Super+Alt+F. hints is a separate install (see README).
	gnome_shortcut 'capsnav: hints' "$HOME/.local/bin/hints" '<Super><Alt>f'
else
	echo "GNOME not found: bind Super+Alt+O to /usr/local/bin/capsnav-switch-monitor"
	echo "and Super+Alt+F to ~/.local/bin/hints yourself for Caps+p and Caps+f."
fi
if ! command -v xdotool >/dev/null; then
	echo "Caps+p needs xdotool: sudo apt install xdotool"
fi
if [ -x "$HOME/.local/bin/hints" ]; then
	# Turns off Alt+label drag (see README), then reload the daemon.
	install -Dm644 hints-config.json "$HOME/.config/hints/config.json"
	systemctl --user restart hintsd 2>/dev/null || true
else
	echo "Caps+f needs hints: see the Click hints section of README.md"
fi

sleep 1
if sudo journalctl -u capsnav-scroll -n 50 -o cat | grep "scroll mode" | tail -1 | grep -q wheel; then
	echo
	echo "Reboot once to finish smooth-scroll setup (libinput loads its settings at login)."
fi
