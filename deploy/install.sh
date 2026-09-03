#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sudo cp "$REPO_DIR/deploy/mtgkiosk.service" /etc/systemd/system/mtgkiosk.service
sudo cp "$REPO_DIR/deploy/mtgkiosk-ui.service" /etc/systemd/system/mtgkiosk-ui.service
sudo cp "$REPO_DIR/deploy/99-mtg-printer.rules" /etc/udev/rules.d/99-mtg-printer.rules

sudo udevadm control --reload-rules
sudo udevadm trigger

python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"

sudo systemctl daemon-reload
sudo systemctl enable --now mtgkiosk.service
sudo systemctl enable --now mtgkiosk-ui.service

echo "Installed. Check status with: sudo systemctl status mtgkiosk mtgkiosk-ui"
