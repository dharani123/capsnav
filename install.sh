#!/usr/bin/env bash
# Install everything capsnav needs: system packages, keyd (built from
# keyd-src) and its config, the smooth-scroll and pointer-motion helper, the Caps+p
# switch-monitor script, hints for Caps+g, and the GNOME shortcuts.
# Run as your normal user; it uses sudo where needed. Safe to re-run.
set -e
cd "$(dirname "$0")"
HINTS_VERSION=0.1.1
need_reboot=

# System packages: build tools, xdotool/xprop/xrandr (Caps+p), hints build deps.
if command -v apt-get >/dev/null; then
	# A broken third-party repo shouldn't stop the install.
	sudo apt-get update || true
	sudo apt-get install -y git curl build-essential python3 python3-dev \
		xdotool x11-utils x11-xserver-utils \
		libcairo2-dev pkg-config cmake libdbus-1-dev libgirepository1.0-dev gir1.2-gtk-3.0
elif command -v dnf >/dev/null; then
	sudo dnf install -y git curl gcc make python3 python3-devel xdotool xprop xrandr \
		cairo-gobject-devel pkgconf-pkg-config cmake dbus-devel gobject-introspection-devel gtk3
else
	echo "No apt-get or dnf: install the packages listed in README.md yourself."
fi

make -C keyd-src
sudo make -C keyd-src install
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
# Pointer motion (Caps+Space+i/j/k/l): same program as a user service, since
# XTest needs your X session. The keyd group lets it read `keyd listen`.
if ! id -nG "$USER" | grep -qw keyd; then
	sudo usermod -aG keyd "$USER"
	need_reboot=1
fi
install -Dm644 capsnav-mouse.service "$HOME/.config/systemd/user/capsnav-mouse.service"
systemctl --user daemon-reload
systemctl --user enable capsnav-mouse
systemctl --user restart capsnav-mouse

sudo install -m755 capsnav-switch-monitor.sh /usr/local/bin/capsnav-switch-monitor

# hints (Caps+g), installed per user with uv into ~/.local. Skipped when the
# pinned version is already there.
if [ "$("$HOME/.local/bin/hints" --version 2>/dev/null)" != "$HINTS_VERSION" ]; then
	uv=$(command -v uv || true)
	if [ -z "$uv" ]; then
		uv_dir=$(mktemp -d)
		curl -LsSf https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 UV_INSTALL_DIR="$uv_dir" sh
		uv=$uv_dir/uv
	fi
	# hints' setup.py writes the hintsd unit using this; ours below replaces it.
	HINTS_EXPECTED_BIN_DIR="$HOME/.local/bin" "$uv" tool install --force \
		"git+https://github.com/AlfredoSequeida/hints@$HINTS_VERSION"
	if [ -n "$uv_dir" ]; then rm -r "$uv_dir"; fi
fi

# What `hints --setup` does, but idempotent (it appends duplicate lines to
# /etc/environment on every run). Accessibility makes apps report their
# buttons; uinput + the input group let hints click.
a11y="ACCESSIBILITY_ENABLED=1 GTK_MODULES=gail:atk-bridge OOO_FORCE_DESKTOP=gnome
GNOME_ACCESSIBILITY=1 QT_ACCESSIBILITY=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1"
for kv in $a11y; do
	if ! grep -q "^${kv%%=*}=" /etc/environment; then
		echo "$kv" | sudo tee -a /etc/environment >/dev/null
		need_reboot=1
	fi
	# Display managers source ~/.xprofile for X sessions.
	if ! grep -qs "${kv%%=*}=" "$HOME/.xprofile"; then
		echo "export $kv" >>"$HOME/.xprofile"
	fi
done
echo uinput | sudo tee /etc/modules-load.d/uinput.conf >/dev/null
sudo modprobe uinput
echo 'KERNEL=="uinput", GROUP="input", MODE:="0660"' | sudo tee /etc/udev/rules.d/80-hints.rules >/dev/null
if ! id -nG "$USER" | grep -qw input; then
	sudo usermod -aG input "$USER"
	need_reboot=1
fi
install -Dm644 hints-config.json "$HOME/.config/hints/config.json"
install -Dm644 hintsd.service "$HOME/.config/systemd/user/hintsd.service"
systemctl --user daemon-reload
systemctl --user enable hintsd
systemctl --user restart hintsd

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
	# Caps+p sends Super+Alt+O, Caps+g sends Super+Alt+F.
	gnome_shortcut 'capsnav: switch monitor' /usr/local/bin/capsnav-switch-monitor '<Super><Alt>o'
	gnome_shortcut 'capsnav: hints' "$HOME/.local/bin/hints" '<Super><Alt>f'
else
	echo "GNOME not found: bind Super+Alt+O to /usr/local/bin/capsnav-switch-monitor"
	echo "and Super+Alt+F to ~/.local/bin/hints yourself for Caps+p and Caps+g."
fi

sleep 1
if ! systemctl is-active --quiet keyd; then
	echo "keyd is not running: check 'journalctl -u keyd -b' and run 'sudo systemctl restart keyd'."
fi
if sudo journalctl -u capsnav-scroll -n 50 -o cat | grep "scroll mode" | tail -1 | grep -q wheel; then
	need_reboot=1
fi
echo
if [ -n "$need_reboot" ]; then
	echo "Done. Reboot once to finish (smooth scroll, accessibility and the input group load at login)."
else
	echo "Done."
fi
