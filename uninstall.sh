#!/usr/bin/env bash
# Remove everything install.sh set up: keyd (and its capsnav config), the
# scroll/pointer/focus helpers and their services, the top-bar icon, the
# libinput quirk and X setting, and the GNOME shortcuts. The keyboard is back
# to normal straight away; reboot once to clear the scroll settings.
# Run as the same user who ran install.sh; it uses sudo where needed. System
# packages (xdotool, python3-gi, ...) are left installed, since other programs
# may use them. Safe to re-run.
cd "$(dirname "$0")"

# User services (pointer motion + top-bar icon, per-app keys, focus follow).
for unit in capsnav-mouse capsnav-appmap capsnav-focus-follow; do
	systemctl --user disable --now "$unit" 2>/dev/null
	rm -f "$HOME/.config/systemd/user/$unit.service"
done
systemctl --user daemon-reload
pkill -f /usr/local/bin/capsnav-indicator
rm -f "$HOME/.config/keyd/app.conf"
rmdir "$HOME/.config/keyd" 2>/dev/null

# GNOME custom shortcuts named "capsnav: ...".
schema=org.gnome.settings-daemon.plugins.media-keys
if gsettings list-schemas 2>/dev/null | grep -qx "$schema"; then
	keep=()
	for p in $(gsettings get $schema custom-keybindings | grep -o "'[^']*'" | tr -d "'"); do
		if gsettings get $schema.custom-keybinding:"$p" name | grep -q "^'capsnav: "; then
			gsettings reset-recursively $schema.custom-keybinding:"$p"
		else
			keep+=("'$p'")
		fi
	done
	if [ ${#keep[@]} -eq 0 ]; then
		gsettings set $schema custom-keybindings "@as []"
	else
		list=$(IFS=,; echo "${keep[*]}")
		gsettings set $schema custom-keybindings "[${list//,/, }]"
	fi
fi

# Root parts: smooth scroll service, keyd and its config, helpers, icons.
sudo systemctl disable --now capsnav-scroll 2>/dev/null
sudo rm -f /etc/systemd/system/capsnav-scroll.service
sudo systemctl disable --now keyd 2>/dev/null
sudo rm -f /etc/keyd/default.conf /etc/keyd/capsnav-nav /etc/keyd/capsnav-mousetype
sudo rmdir /etc/keyd 2>/dev/null
sudo rm -f /etc/systemd/system/keyd.service.d/capsnav-restart.conf
sudo rmdir /etc/systemd/system/keyd.service.d 2>/dev/null
sudo make -C keyd-src uninstall  # also deletes the keyd group
sudo systemctl daemon-reload
sudo rm -rf /etc/capsnav /usr/local/share/capsnav
sudo rm -f /usr/local/bin/capsnav-scroll /usr/local/bin/capsnav-indicator \
	/usr/local/bin/capsnav-mappings /usr/local/bin/capsnav-switch-monitor \
	/usr/local/bin/capsnav-switch-workspace /usr/local/bin/capsnav-focus-follow \
	/usr/local/share/icons/hicolor/scalable/status/capsnav-mouse.svg \
	/usr/local/share/icons/hicolor/scalable/status/capsnav-keyboard.svg \
	/etc/X11/xorg.conf.d/50-capsnav-scroll.conf
sudo touch /usr/local/share/icons/hicolor 2>/dev/null

# The libinput quirk install.sh appended to a shared file: take out just that
# block, and the file too if nothing else is left in it.
quirks=/etc/libinput/local-overrides.quirks
if sudo grep -qs "MatchName=capsnav smooth scroll" "$quirks"; then
	sudo python3 -I - "$quirks" system/capsnav.quirks <<'EOF'
import sys
path, block = sys.argv[1], open(sys.argv[2]).read()
text = open(path).read()
text = text.replace("\n" + block, "", 1).replace(block, "", 1)
if text.strip():
    open(path, "w").write(text)
else:
    import os
    os.remove(path)
EOF
fi

echo
echo "capsnav removed. Reboot once to finish (scroll settings and the keyd"
echo "group clear at login). You can delete this folder afterwards."
