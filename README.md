# MTG Kiosk

A Raspberry Pi appliance that sits in the middle of the table during Magic: The
Gathering games. It boots straight into a fullscreen touch app — no desktop, no
launcher — and self-heals if anything crashes.

| | |
|---|---|
| Board | Raspberry Pi 5, 4 GB |
| Display | 7" DSI, 800x480, capacitive touch |
| Printer | miemieyo M4202, 203 DPI direct thermal, driven raw over TSPL2 |
| OS | Raspberry Pi OS Desktop (64-bit) |

## What it does

- **Life counter** — 2 to 8 players. The far row is rotated 180°, so players
  across the table read their own total the right way up. Commander damage,
  poison counters, and press-and-hold to move fast. Survives a reboot mid-game.
- **Card lookup** — search 34.6k cards by name on the on-screen keyboard. Card
  images are fetched from Scryfall on demand and cached.
- **Random card** — reachable from any screen via the dice button.
- **Horde mode** — pick a creature type and a difficulty; it builds a horde deck
  and runs the game loop.
- **Print** — any card's text to a 3x2in thermal label, to stick on a bulk card.
- **Settings** — printer status, wifi (including networks that aren't
  broadcasting), self-update from git, and the card database download.

Everything except the image fetch and the database download works with no
network at all.

## Install on the Pi

```bash
git clone https://github.com/D-lougheed/MTG_Box.git ~/mtg-kiosk
cd ~/mtg-kiosk
bash deploy/install.sh
```

That installs both systemd units, the printer udev rule, and a sudoers rule
scoped to exactly one command (see *Updating* below), then starts the app.

Then **download the card database** — Settings → Update card database. It pulls
about 24 MB from Scryfall and takes a few minutes on Pi wifi. Nothing else
depends on the network, but the lookup, random card and horde screens all need
this before they do anything useful.

You can also build it from a terminal:

```bash
python scripts/ingest_cards.py
```

## Updating

Settings → Check for updates → Install update & restart. That does a
`git pull --ff-only`, reinstalls requirements, and restarts the service.

`--ff-only` is deliberate: a local edit on the Pi makes the update fail loudly
rather than silently clobbering it. If that happens, `git status` on the Pi will
show what diverged.

Changes to anything under `deploy/` — systemd units, the udev rule, the sudoers
rule — are **not** picked up by the in-app update. Re-run `bash deploy/install.sh`
after pulling those.

## Layout

```
src/mtgkiosk/
  app.py           FastAPI app: serves the UI, exposes the JSON API
  cards.py         Card record and every query against the local database
  ingest.py        Builds the database from Scryfall's bulk export
  images.py        On-demand card image cache
  horde.py         Horde deck generation
  updater.py       git-based self-update
  wifi.py          nmcli scan/connect
  printer/
    tspl.py        TSPL2 command builder (pure)
    raster.py      PIL image -> 1-bit packed bytes (pure)
    transport.py   The only module that touches hardware
    device.py      ThermalPrinter facade
    card_label.py  Renders a card to a 609x406 dot label
web/               UI. Plain scripts and CSS, no build step
deploy/            systemd units, udev rule, sudoers rule, install.sh
docs/superpowers/  Design specs and implementation plans
data/              Card database and image cache. Generated, gitignored
```

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The frontend has **no build step and no npm**, on purpose: updates are
`git pull` plus a restart, and `npm install` on a Pi over wifi is the step that
breaks at the worst possible moment. Frontend changes are verified by driving
the real UI in a browser at 800x480.

To run the app locally:

```bash
.venv/bin/python -m uvicorn mtgkiosk.app:app --host 127.0.0.1 --port 8080 --app-dir src
```

## Design notes

Each slice has a spec and a plan under `docs/superpowers/`, including the
mistakes — the specs are amended in place when reality disagreed with them, and
the plans record what had to be corrected during the build. Worth reading before
changing anything non-obvious; several of the decisions look arbitrary until you
know what went wrong the first time.
