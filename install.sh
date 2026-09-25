#!/usr/bin/env bash
# Build/install keyd from keyd-src and apply the capsnav config.
set -e
cd "$(dirname "$0")"
make -C keyd-src
sudo make -C keyd-src install
sudo cp default.conf /etc/keyd/default.conf
sudo systemctl enable --now keyd
sudo keyd reload
