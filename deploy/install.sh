#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sudo cp "$REPO_DIR/deploy/mtgkiosk.service" /etc/systemd/system/mtgkiosk.service
sudo cp "$REPO_DIR/deploy/mtgkiosk-ui.service" /etc/systemd/system/mtgkiosk-ui.service
sudo cp "$REPO_DIR/deploy/99-mtg-printer.rules" /etc/udev/rules.d/99-mtg-printer.rules

sudo udevadm control --reload-rules
sudo udevadm trigger

sudo visudo -c -f "$REPO_DIR/deploy/mtgkiosk-sudoers"
sudo cp "$REPO_DIR/deploy/mtgkiosk-sudoers" /etc/sudoers.d/mtgkiosk
sudo chmod 0440 /etc/sudoers.d/mtgkiosk

python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"

sudo systemctl daemon-reload
sudo systemctl enable mtgkiosk.service mtgkiosk-ui.service

# restart, not `enable --now`. On a first install the two are the same thing,
# but on a RE-RUN the units are already running, so --now is a no-op: the
# freshly pulled code sits on disk and the old process keeps serving. That is
# exactly the case this script exists for, since the one thing the in-app
# updater can never install is a repair to its own sudoers grant.
sudo systemctl restart mtgkiosk.service mtgkiosk-ui.service

echo "Installed and restarted. Running:"
git -C "$REPO_DIR" --no-pager log --oneline -1
echo "Check status with: sudo systemctl status mtgkiosk mtgkiosk-ui"
