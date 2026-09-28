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
sudo install -m755 capsnav-scroll.py /usr/local/bin/capsnav-scroll
sudo install -m644 capsnav-scroll.service /etc/systemd/system/capsnav-scroll.service
sudo systemctl daemon-reload
sudo systemctl enable capsnav-scroll
sudo systemctl restart capsnav-scroll
