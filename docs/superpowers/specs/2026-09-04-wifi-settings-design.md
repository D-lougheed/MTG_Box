# Wifi Settings — Design

**Date:** 2026-09-04
**Status:** Approved, not yet implemented
**Builds on:** Slice 1 (kiosk shell + printer driver), fully deployed and verified on the physical Pi as of this date.

## Background

Slice 1's Settings screen can *read* the current wifi state (`_wifi_state()` in `app.py`, via `nmcli -t -f STATE general`) but has no way to *join* a new network. Discovered as a real gap during Task 11's hardware deployment: the kiosk has a touchscreen and no physical keyboard, and the only way to change its wifi today is connecting over VNC and editing NetworkManager by hand. This spec adds a proper in-kiosk flow for that.

Confirmed during investigation (not assumed): the systemd backend runs as `User=admin`, and `admin` is already in the `netdev` group — the same group Raspberry Pi OS's own desktop wifi applet relies on to manage networks without a root password prompt. A live scan (`nmcli device wifi list`) already worked with no elevation. This means the backend can very likely call `nmcli` directly for both scanning and connecting, with no privileged-helper process needed — to be confirmed for real once `connect` (not just `list`) is exercised against real hardware.

Also relevant: because the kiosk UI is served entirely from `127.0.0.1` by the local backend, this screen works even if the Pi currently has **no** wifi connection at all — nothing about loading the page itself depends on having network access. That makes this the actual recovery path for a Pi that's lost its wifi, not just a convenience.

## Goals

1. From the Settings screen, scan for nearby wifi networks and show them, strongest signal first.
2. Tap a network, enter its password (skipped for open networks) on an in-page virtual keyboard, connect.
3. Report success or failure plainly. No parsing of *why* a connection failed — out of scope (see Non-goals).

## Non-goals

- Managing/forgetting previously-connected networks. NetworkManager already remembers connections it's joined; this feature only adds new ones.
- Distinguishing failure causes (wrong password vs. out of range vs. timeout). All failures show the same message.
- WPA2-Enterprise or any auth beyond a single shared password / open network. Not a realistic need for a home kiosk.
- A privileged-helper process for `nmcli`. Believed unnecessary given the `netdev` group finding above; if real-hardware testing proves otherwise, that becomes a follow-up, not part of this spec.

## Key decisions

### Build the on-screen keyboard into the page, not `matchbox-keyboard`

The Pi's display manual documents installing `matchbox-keyboard` (a standalone X11 on-screen keyboard) for exactly this kind of need. Rejected in favor of a keyboard built directly into the web page (plain HTML/CSS/JS, matching the rest of this frontend) because integrating an external X11 application would mean the backend spawning and killing a separate OS process in sync with DOM focus events in the browser — a new category of moving parts nothing else in this app has, with real uncertainty around window positioning and z-ordering relative to the kiosk's fullscreen Chromium window. An in-page keyboard has none of that: it's just another piece of UI state, testable and stylable the same way as everything else in `web/`.

### Password field defaults to visible text, not masked

A masked password field is the right default when you trust your own typing on a device you're used to. Here, entry happens via an on-screen keyboard on a touchscreen, for a value that's often 15+ random characters — mistyping is common and not being able to see what you typed before committing is a worse experience than the modest privacy cost of a visible field on a home kiosk. A show/hide toggle is included so this can be masked when wanted, but visible is the default.

### De-duplicate scan results by SSID, keep the strongest signal

A real scan on this hardware returned the same home network name five times (multiple mesh access points). Showing five identical-looking entries is confusing; NetworkManager's `nmcli device wifi connect <SSID>` already picks the best AP for a given SSID on its own, so there's no functional reason to show more than one row per network name.

## Architecture

### Navigation

A new view, `view-wifi`, added to the existing flat view-switching scheme in `web/js/app.js` (`showView()` — no new navigation mechanism). Reached via a new button on the Settings screen: **"Connect to wifi network."** Its Back button targets `settings`, not `menu` — the only view in the app whose Back button doesn't return to the main menu, since it's reached from Settings specifically.

### Backend — two new endpoints on the existing FastAPI app

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/wifi/scan` | Scan for networks, de-duplicated by SSID, sorted by signal strength descending |
| `POST` | `/api/wifi/connect` | Join a network: body `{"ssid": str, "password": str \| null}` |

A new module, `src/mtgkiosk/wifi.py`, mirrors the shape of `updater.py`:

```python
class WifiError(Exception):
    pass

@dataclass
class WifiNetwork:
    ssid: str
    signal: int       # 0-100, from nmcli
    secured: bool

def scan() -> list[WifiNetwork]: ...
def connect(ssid: str, password: str | None) -> None: ...
```

`scan()` runs `nmcli -t -f SSID,SIGNAL,SECURITY device wifi list`, parses the colon-separated output, drops entries with an empty SSID (nmcli reports hidden networks this way), groups by SSID keeping the highest `SIGNAL`, and returns networks sorted by signal descending. `connect()` runs `nmcli device wifi connect <ssid>` plus `password <password>` only when a password is given, checks the subprocess's exit code, and raises `WifiError` with nmcli's stderr on failure — same shape as `UpdateError`, including the same `timeout=` and credential-scrubbing precautions `updater.py` already established (a wifi password in an error message is exactly the kind of thing that must never leak into a log or HTTP response body).

`app.py` gains two routes wrapping these, translating `WifiError` to an HTTP error response — matching the existing `PrinterError` → 503 / `UpdateError` → 502 pattern. A connect failure returns 502-equivalent (a wifi/network failure, not a client input error) with a generic `"Couldn't connect. Check the password and try again."` detail — deliberately not nmcli's raw stderr, since Non-goals rules out cause-parsing and raw nmcli text is exactly the kind of thing the project has already been burned by leaking (see `updater.py`'s credential-scrubbing history).

### Frontend

`view-wifi` shows a scanned network list (SSID, a signal-strength indicator, a lock icon for secured networks) fetched from `GET /api/wifi/scan` on view entry. An empty result (radio off, nothing in range) shows an explicit "No networks found" message rather than a blank list, with a way to re-scan. Tapping a secured network reveals a password field and the on-screen keyboard; tapping an open network skips straight to a Connect button. The Connect button disables itself for the duration of the request, matching the existing pattern from self-test and update-check.

The keyboard is a new, reusable component (`web/js/keyboard.js` or folded into `app.js` — implementation plan decides): a standard QWERTY layout with shift and backspace, writing into whichever input last focused it. It has no knowledge of wifi specifically, so it's reusable if a future feature ever needs text entry (e.g., Slice 4's card lookup search).

## Error handling

Same governing principle as the rest of Slice 1: a wifi problem must never take down the kiosk. `wifi.py`'s functions never let a raw `OSError`/`subprocess` exception escape — everything becomes `WifiError`, caught at the API boundary, surfaced as a plain message in the UI per the approved "just success or failure" scope decision.

## Testing

`wifi.py`'s `scan()` parsing/dedup logic and `connect()`'s argument construction and error translation get unit tests with a mocked `subprocess.run`, following `updater.py`'s existing test pattern — no real wifi hardware needed for this layer. The view and keyboard component are verified manually against the running app, consistent with how `web/` has been tested throughout this project; the implementation plan's manual-verification checklist must include an actual connect attempt against real hardware, since the `netdev`-group permission theory in Background is confirmed for *scanning* only, not yet for *connecting*.

---

## Addendum — 2026-09-05: manual network entry, keyboard overlap, asset caching

Three follow-on changes, recorded here because a code review found the first one
had already silently violated the "password field defaults to visible" decision
above, precisely because there was no written record of the increment.

### Connect to a network that isn't in the scan list

The scan-and-tap flow can't reach a hidden SSID, or one that simply isn't
broadcasting at that moment. A "Connect to a different network" button opens a
second form with a free-text SSID field, a "secured network" checkbox, and the
same password row.

No backend change was needed: `POST /api/wifi/connect` already accepted an
arbitrary SSID string and never validated it against the scan results.

The two forms are kept **separate rather than unified into one mode-switching
form**. Overloading the existing form would have meant threading a mode flag
through `selectWifiNetwork` and the connect handler — code that had already
been through four review rounds and had subtle stale-response bugs fixed in it.
A parallel form duplicates a password toggle and a connect handler, which is the
cheaper trade against regressing a hardened path.

Because there is no "currently selected network" object for freeform entry, the
manual form's stale-response guard uses an **incrementing token** captured before
the fetch and re-checked after each `await`, rather than the scanned flow's
object-identity comparison. Opening either form invalidates the other.

### The keyboard was covering the controls beneath it

The on-screen keyboard is a `position: fixed` overlay. At the touch-friendly key
height it occupies roughly 252px of the 480px screen, which put it directly on
top of the secured checkbox and the Connect/Cancel buttons — and the containing
`.settings-scroll` had no overflow, so there was no scroll room to move them
clear. They were invisible and untappable.

Fixed by adding `padding-bottom: 280px` to `.settings-scroll` **only while
`body.keyboard-open`**, which creates that scroll room, plus scrolling the
focused input into view when the keyboard opens. 280px is the keyboard's 256px
measured height (5 rows x 44px, plus row margins and container padding) with a
little clearance.

This is latent in any future view that shows the keyboard, so the rule is keyed
off a body class rather than anything wifi-specific.

### Static assets could go stale across a self-update

`StaticFiles` sends no cache-control header, so browsers fall back to heuristic
caching — which was observed serving a stale `keyboard.js` through a full page
reload during testing. On the Pi this matters more than it looks: restarting
`mtgkiosk.service` cascades (via `PartOf=`) into restarting the Chromium UI, but
Chromium's disk cache lives in a persistent `--user-data-dir` and survives that,
so a self-update could leave old JS running against a new backend.

Every response now carries `Cache-Control: no-cache`. Deliberately `no-cache`
and not `no-store`: `StaticFiles` already handles conditional requests via
ETag/Last-Modified, so this forces revalidation while still allowing 304s,
rather than forcing a full re-download of every asset on every load.
