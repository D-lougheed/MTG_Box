# MTG Kiosk — Slice 1: Kiosk Shell + Printer Driver

**Date:** 2026-09-03
**Status:** Approved, not yet implemented
**Slice:** 1 of 5

## Background

A Raspberry Pi appliance that sits on the table during Magic: The Gathering games. It runs a touchscreen app providing a life counter, a horde-mode game engine, card lookup backed by an offline database, a random-card roller, and the ability to print card text to a thermal label printer.

That full scope is a platform, not a feature, so it is decomposed into five slices (see *Slice Roadmap* below). This document specs **Slice 1 only**.

### Hardware

| Component | Detail |
|---|---|
| Board | Raspberry Pi 5, 4 GB |
| Display | 7" DSI, 800x480 IPS, capacitive touch (~2 point), 15-pin 1.0 mm FPC via 22-to-15 adapter |
| Printer | miemieyo M4202 / M4201, 4x6 direct thermal, 203 DPI, monochrome, USB, self-powered |
| OS | Raspberry Pi OS Desktop (64-bit) |

Useful derived constant: a real Magic card (63 x 88 mm) is 503 x 703 dots at 203 DPI — reference only. **Actual production stock for this project is 3in x 2in (609 x 406 dots at 203 DPI), confirmed 2026-09-03**: a landscape overlay label applied on top of an existing bulk/common card, not a full-card replica. This locks in the print path as text-only by design (name, mana cost, type line, rules text), not an attempted card-art reproduction.

## Goals

1. Pi boots directly into a fullscreen kiosk app. No desktop, no launcher, self-healing on crash.
2. Main menu with five entry points; four are stubs in this slice.
3. A persistent global random-card affordance, reachable from any screen (stub action).
4. A **fully functional** Settings screen: printer status, self-test print, git update, current commit, wifi state.
5. A printer library where the majority of the code is unit-testable without hardware attached.

## Non-goals

Explicitly out of scope for Slice 1, to be delivered by later slices:

- Card database, Scryfall integration, bulk ingest
- Life counter logic or UI
- Horde-mode engine
- Card lookup UI, card image caching
- CUPS integration of any kind
- Multi-user or network access (binds to loopback only)

## Key decisions

### No CUPS — drive the printer raw over TSPL

The app prints card-shaped output at an exact physical size. CUPS rasterizes through a PPD that imposes its own margins and scaling, which fights pixel-exact output. TSPL's `BITMAP` command accepts 1-bit packed data directly, so we render with Pillow at exactly 203 DPI and ship bytes. This is deterministic, and avoids depending on an ARM64 PPD that may not exist for this brand.

CUPS can be added later as a purely additive convenience for printing from other machines.

### No frontend build step

ES modules and plain CSS with custom properties; dependencies vendored into the repo.

Driven by the update mechanism: `git pull` + restart is reliable. Requiring `npm install && npm run build` on a Pi over wifi is slow and fragile, and would fail at the worst moment. If UI complexity later earns it, we add Vite and commit `dist/`.

### Transport abstraction isolates the one unknown

How the printer enumerates is not yet known (see *Blocked*). The design confines that uncertainty to a single module so roughly 80% of the printer code can be written and tested before the hardware is characterized.

## Architecture

Two systemd units, both `Restart=always`:

```
mtgkiosk.service     -> uvicorn/FastAPI on 127.0.0.1:8080   (serves UI + JSON API)
mtgkiosk-ui.service  -> chromium --kiosk http://127.0.0.1:8080
```

### Directory layout

```
mtg-kiosk/
  src/mtgkiosk/
    app.py            FastAPI application, route definitions
    printer/
      tspl.py         TSPL command builder (pure)
      raster.py       PIL image -> 1-bit packed bytes (pure)
      transport.py    Hardware I/O, two implementations
      device.py       ThermalPrinter facade
    updater.py        git fetch/pull, restart scheduling
  web/
    index.html
    css/
    js/
    vendor/
  deploy/
    mtgkiosk.service
    mtgkiosk-ui.service
    99-mtg-printer.rules
    install.sh
  tests/
  docs/superpowers/specs/
```

## Components

Each component below states what it does, how it is used, and what it depends on.

### `printer/tspl.py`

- **Does:** Builds TSPL2 command byte sequences — `SIZE`, `GAP`, `DIRECTION`, `CLS`, `TEXT`, `BITMAP`, `PRINT`.
- **Used as:** Pure functions; arguments in, `bytes` out. No I/O.
- **Depends on:** Nothing.
- **Testable:** Fully, byte-exact, no hardware.

### `printer/raster.py`

- **Does:** Converts a Pillow image into 1-bit packed rows suitable for TSPL `BITMAP`, with optional Floyd-Steinberg dithering and plain-threshold modes.
- **Used as:** `pack(img, dither=False) -> (width_bytes, height, bytes)`
- **Depends on:** Pillow.
- **Testable:** Fully, known image to known bytes, no hardware.

### `printer/transport.py`

- **Does:** The only module that touches hardware. Writes byte buffers to the printer.
- **Used as:** One interface, two implementations selected at runtime by what enumerated:
  - `UsbLpTransport` — writes to `/dev/mtgprinter` (a udev symlink to `/dev/usb/lp0`)
  - `PyUsbTransport` — raw endpoint writes via pyusb, for the vendor-class case
- **Depends on:** OS device node, or pyusb.
- **Testable:** Via mocks only. This is the deliberate concentration of untestable surface.

### `printer/device.py`

- **Does:** The public facade the rest of the app uses. Composes the three modules above and owns connection state.
- **Used as:**

```python
printer.is_connected() -> bool
printer.print_text_label(lines, size) -> None
printer.print_image(img, size) -> None
printer.self_test() -> None
```

- **Depends on:** `tspl`, `raster`, `transport`.

### `updater.py`

- **Does:** Checks for and applies updates from the git remote.
- **Used as:** `check() -> UpdateStatus`, `apply() -> None`
- **Depends on:** `git` binary, `systemd-run`, network.

### `app.py`

- **Does:** FastAPI app. Serves static UI from `web/` and exposes the JSON API.
- **Depends on:** `printer.device`, `updater`.

### `web/`

- **Does:** The kiosk UI. Main menu, global random-card affordance, Settings screen.
- **Depends on:** The JSON API. No build tooling.

## API surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/status` | Printer connected, commit hash, wifi state, app version |
| `POST` | `/api/printer/selftest` | Print a physical test label |
| `GET` | `/api/update/check` | Whether the remote is ahead, and by what |
| `POST` | `/api/update/apply` | Pull and schedule restart |

Binds to `127.0.0.1` only. Not reachable from the network.

## Data flow

**Boot:** power on → systemd starts `mtgkiosk.service` → systemd starts `mtgkiosk-ui.service` → Chromium loads `127.0.0.1:8080` fullscreen → main menu.

**Self-test:** UI button → `POST /api/printer/selftest` → `device.self_test()` → `tspl` builds bytes → `transport` writes to device → label emerges.

The self-test label is defined as: a text line reading `MTG KIOSK OK`, the current commit short hash, a timestamp, and a 100 x 100 dot solid black square. The square exercises the `BITMAP`/raster path, the text exercises the `TEXT` path, so one label proves both code paths end to end.

**Status polling:** the UI polls `GET /api/status` every 5 seconds and re-renders the printer badge from the response. No push channel in this slice; a 5 second lag on noticing an unplugged printer is acceptable and avoids a WebSocket dependency.

**Update:** UI button → `GET /api/update/check` shows result → user confirms → `POST /api/update/apply` → `git pull --ff-only` → reinstall requirements if changed → `systemd-run --on-active=2 systemctl restart mtgkiosk` → HTTP response returns before the process dies → Chromium reconnects on restart.

## Error handling

**Governing rule: a printer problem must never take down the kiosk.**

| Condition | Behaviour |
|---|---|
| Printer unplugged / absent at boot | `is_connected()` false; Settings shows an offline badge; print actions disabled with a visible reason |
| Write fails mid-print | Caught in `device.py`, logged, surfaced to UI. Never propagated to the shell |
| Backend crash | `Restart=always` brings it back; Chromium retries the connection |
| Chromium crash | `Restart=always` |
| `git pull` conflicts with local edits | `--ff-only` makes it fail loudly rather than silently clobbering. Failure reported in UI; no partial update |
| Network down during update check | Reported as "cannot reach remote", not an error state |

## Testing strategy

- **Unit, no hardware:** `tspl.py` and `raster.py` get byte-exact assertions. This is the bulk of the printer logic and it is fully covered before the printer is ever plugged in.
- **Mocked:** `transport.py` and `device.py` against a fake transport that records writes.
- **Mocked:** `updater.py` against a temporary local git repo, including the conflict case.
- **Manual, hardware:** the Settings self-test button printing a real label. This is the only test requiring the physical printer.

## Blocked / open questions

These do not block starting implementation, because the transport abstraction contains them. They do block completing `transport.py`.

1. ~~SSH is not enabled on the Pi.~~ **Resolved 2026-09-03.** SSH and VNC are enabled. Host `192.168.1.96`, user `admin`. Key-based access being set up now via a dedicated `mtgkiosk_pi` keypair (see below) rather than the default password.
2. ~~Printer enumeration is uncharacterized.~~ **Resolved 2026-09-03.** Confirmed via `dmesg`: kernel `usblp` binds directly — `usblp0: USB Bidirectional printer dev 3 if 0 alt 0 proto 2 vid 0x2D37 pid 0x81F7`. This is the easy path from the design: `UsbLpTransport` writing to `/dev/usb/lp0`, no `pyusb` required. `lsusb` confirms the device as `2d37:81f7 Zhuhai Poskey Technology Co.,Ltd M4202` (Poskey is the OEM behind the miemieyo-branded unit).
3. ~~Printer command language is presumed TSPL2, not yet confirmed.~~ **Resolved 2026-09-03.** Confirmed via the printer's own `SELFTEST` command, which produced a standard TSC-format diagnostic label (`Code page` / `Speed` / `Density` / `size` / `gap` / `reference` fields). Also revealed the printer's default measurement unit is **millimeters, not inches** — an initial hand-built test using unitless `SIZE 4,6` (intending inches) was silently interpreted as 4mm x 6mm, producing a tiny declared print area that a text position of (100,100) dots fell entirely outside of. **`tspl.py` must always emit explicit unit suffixes** (`SIZE 101.6 mm,152.4 mm`, not `SIZE 4,6`) rather than relying on the printer's ambient default. Diagnostic label also reports code page **PC936** (a Chinese/GBK-family code page) as the printer's default text encoding — irrelevant for plain-ASCII card names, but relevant if `raster.py`/`tspl.py` ever needs to emit accented characters (e.g. card names with diacritics); revisit via TSPL2's `CODEPAGE` command if that comes up in Slice 2.
4. **The git remote does not exist yet.** The update button requires one. Needs to be created and the Pi given read access.
5. **The udev rule can now be pinned exactly**, since the VID:PID is known: `2d37:81f7`.
6. **Direct SSH from the development machine is blocked, cause unconfirmed.** `sshd` is healthy on the Pi (confirmed via loopback `ssh admin@localhost`) and no firewall exists on either the Pi (no `ufw`/`iptables`/`fail2ban`/`nft` rules) or the Windows dev machine (no VPN/EDR process, zero outbound firewall block rules, Defender Network Protection disabled, direct on-link route to the Pi's subnet). The connection is actively refused (immediate RST) rather than timing out, which points at the router/AP possibly injecting the reset — untested. **Decision: not worth blocking on.** All Slice 1 development proceeds via commands relayed through the existing VNC session, which has proven reliable for every step so far. Revisit only if VNC-relay becomes a real friction point.

7. **Printer exhibits intermittent USB disconnects under sustained load** (motor and heater active together), confirmed via `dmesg`: it reconnects as fast as 14ms after a drop — too fast to be a physical unplug, pointing at an electrical/signal issue. The power-starvation hypothesis was ruled out (printer has its own separate power supply, confirmed connected). Untested candidate causes: a marginal/unshielded USB data cable, a ground loop between the Pi's and printer's independent power supplies, or a firmware quirk on this OEM board (identifies internally as `GEZHI`, not `Poskey`, despite the `2d37:81f7` VID:PID — likely a relabeled shared reference design). **Deferred by decision 2026-09-03** — proceeding to Slice 1 software work; revisit once back on the printer, testing at the real 3in x 2in label size rather than the 4in x 6in stock used during initial bring-up.

### Security note

The Pi's login is currently the default `admin` / `admin`, with SSH now reachable on the LAN. Worth changing once key-based auth is confirmed working — at that point the password stops being needed day to day anyway, so there's no convenience cost to rotating it. Not treated as blocking; noted here so it doesn't get lost.

## Slice roadmap

Context only. Each later slice gets its own spec.

| Slice | Contents | Depends on |
|---|---|---|
| **1** | **Kiosk shell + printer driver + update mechanism** | **—** |
| 2 | Card data layer (SQLite from Scryfall bulk), random card, print button | 1 |
| 3 | Life counter, up to 8 players | 1 |
| 4 | Card lookup UI, on-demand image cache | 1, 2 |
| 5 | Horde-mode engine | 1, 2, 3 |

### Established facts relevant to later slices

- Scryfall bulk data as of 2026-09-02: Oracle Cards 24.5 MB, Default Cards 78 MB, All Cards 392 MB, Rulings 5 MB — all compressed. The 10 GB offline budget is not a constraint for card *text*.
- Bulk data contains image **URLs, not images**. Full offline art would be roughly 11 GB and is discouraged by Scryfall. Images are therefore an on-demand cached nicety for the lookup screen only.
- The printer is monochrome 203 DPI, so **the print path never needs card art** — card text renders crisply, card images do not.
- Production label size is confirmed as **3in x 2in (609 x 406 dots at 203 DPI)**, not full card size — an overlay label for an existing bulk card. Slice 2's print layout should design for this canvas, not a 63x88mm card-sized one.
- 8 players on 800x480 is a 4x2 grid at ~200x240 px each, on a ~2-point digitizer. Simultaneous input by eight people is not physically possible; the life counter design must account for this.
