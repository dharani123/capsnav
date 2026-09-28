#!/usr/bin/env bash
# Build/install keyd from keyd-src, apply the capsnav config, and install the
# smooth-scroll helper.
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

sleep 1
if sudo journalctl -u capsnav-scroll -n 50 -o cat | grep "scroll mode" | tail -1 | grep -q wheel; then
	echo
	echo "Reboot once to finish smooth-scroll setup (libinput loads its settings at login)."
fi
