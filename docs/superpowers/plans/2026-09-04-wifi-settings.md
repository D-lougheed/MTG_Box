# Wifi Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add scan-and-connect wifi management to the kiosk's Settings screen, so the device can join a new network from its own touchscreen with no VNC access needed.

**Architecture:** A new `wifi.py` module wraps `nmcli` for scanning and connecting, mirroring `updater.py`'s error-handling shape. Two new FastAPI endpoints expose it. A new, wifi-agnostic on-screen keyboard component (`web/js/keyboard.js`) provides text entry on a screen with no physical keyboard; a new `view-wifi` frontend screen wires scan results, the keyboard, and the connect flow together.

**Tech Stack:** Same as the rest of the project — Python 3.11+/FastAPI/pytest on the backend, plain HTML/CSS/JS with no build step on the frontend.

Reference: [`docs/superpowers/specs/2026-09-04-wifi-settings-design.md`](../specs/2026-09-04-wifi-settings-design.md)

---

## Task 1: Wifi Scan/Connect Module (`wifi.py`)

**Files:**
- Create: `src/mtgkiosk/wifi.py`
- Create: `tests/test_wifi.py`

- [ ] **Step 1: Write the failing tests, `tests/test_wifi.py`**

```python
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from mtgkiosk.wifi import WifiError, WifiNetwork, connect, scan


def _fake_result(stdout="", stderr="", returncode=0):
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


def test_scan_parses_networks():
    fake_output = "MyNetwork:80:WPA2\nOpenNet:60:\n"
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stdout=fake_output)) as mock_run:
        networks = scan()
    assert networks == [
        WifiNetwork(ssid="MyNetwork", signal=80, secured=True),
        WifiNetwork(ssid="OpenNet", signal=60, secured=False),
    ]
    assert mock_run.call_args.args[0] == ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"]


def test_scan_deduplicates_by_ssid_keeping_strongest_signal():
    fake_output = "TheGuild:40:WPA2\nTheGuild:75:WPA2\nTheGuild:60:WPA2\n"
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stdout=fake_output)):
        networks = scan()
    assert networks == [WifiNetwork(ssid="TheGuild", signal=75, secured=True)]


def test_scan_sorts_by_signal_descending():
    fake_output = "Weak:20:\nStrong:90:\nMedium:50:\n"
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stdout=fake_output)):
        networks = scan()
    assert [n.ssid for n in networks] == ["Strong", "Medium", "Weak"]


def test_scan_drops_hidden_networks_with_empty_ssid():
    fake_output = ":45:WPA2\nRealNetwork:70:\n"
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stdout=fake_output)):
        networks = scan()
    assert [n.ssid for n in networks] == ["RealNetwork"]


def test_scan_unescapes_colons_in_ssid():
    fake_output = "Office\\:Wifi:65:WPA2\n"
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stdout=fake_output)):
        networks = scan()
    assert networks == [WifiNetwork(ssid="Office:Wifi", signal=65, secured=True)]


def test_scan_raises_wifi_error_on_nonzero_exit():
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stderr="nmcli error", returncode=1)):
        with pytest.raises(WifiError):
            scan()


def test_scan_raises_wifi_error_on_timeout():
    with patch("mtgkiosk.wifi.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="nmcli", timeout=10)):
        with pytest.raises(WifiError):
            scan()


def test_connect_includes_password_when_given():
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result()) as mock_run:
        connect("MyNetwork", "hunter2")
    assert mock_run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "MyNetwork", "password", "hunter2"]


def test_connect_omits_password_for_open_network():
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result()) as mock_run:
        connect("OpenNet", None)
    assert mock_run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "OpenNet"]


def test_connect_raises_wifi_error_on_failure():
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(returncode=1)):
        with pytest.raises(WifiError):
            connect("MyNetwork", "wrongpassword")


def test_connect_error_message_never_contains_the_password():
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stderr="Error: hunter2 rejected", returncode=1)):
        try:
            connect("MyNetwork", "hunter2")
            assert False, "expected WifiError"
        except WifiError as e:
            assert "hunter2" not in str(e)


def test_connect_raises_wifi_error_on_timeout():
    with patch("mtgkiosk.wifi.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="nmcli", timeout=30)):
        with pytest.raises(WifiError):
            connect("MyNetwork", "hunter2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_wifi.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mtgkiosk.wifi'`

- [ ] **Step 3: Write `src/mtgkiosk/wifi.py`**

*(Correction note, added after four review rounds during implementation: the code below is the original draft. The real file diverged substantially — `scan()`/`connect()`'s timeout handling was restructured so `raise` happens after the `try/except` fully exits rather than inside the `except` clause, which is required for `__context__` to genuinely become `None` rather than merely hidden by `__suppress_context__` (a `from None` inside the except block, tried first, turned out insufficient); the two functions' duplicated timeout scaffolding was extracted into a shared `_run_nmcli()` helper, which also gained `OSError` handling for a missing/unreadable `nmcli` binary; the docstring's "a complete, unambiguous fix" claim was corrected to not overstate what scrubbing can guarantee, since a function that needs a plaintext secret as a parameter can never prevent that secret from appearing in its own frame locals if something captures those directly. See `src/mtgkiosk/wifi.py` itself for the current, correct version — it is not reproduced here in full given the extent of the changes.)*

```python
"""Wifi scan/connect via nmcli.

connect() scrubs the password out of any error message before raising -
unlike updater.py's credential scrubbing (which has to guess at credential
shapes in arbitrary text), this function receives the exact secret value
as a parameter, so a plain string replacement is a complete, unambiguous
fix rather than a best-effort regex.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


class WifiError(Exception):
    pass


@dataclass
class WifiNetwork:
    ssid: str
    signal: int
    secured: bool


def _parse_terse_line(line: str) -> list[str]:
    # nmcli -t output escapes a literal ':' as '\:' and '\' as '\\'.
    # Split on unescaped ':' only, then unescape each field. Known limitation:
    # an SSID containing multiple consecutive backslashes before a colon can
    # still misparse - not worth chasing further for a real-world SSID.
    fields = re.split(r"(?<!\\):", line)
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in fields]


def scan(timeout: float = 10) -> list[WifiNetwork]:
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise WifiError(f"scan timed out after {timeout}s") from e
    if result.returncode != 0:
        raise WifiError(result.stderr.strip())

    best_by_ssid: dict[str, WifiNetwork] = {}
    for line in result.stdout.splitlines():
        fields = _parse_terse_line(line)
        if len(fields) < 3:
            continue
        ssid, signal_str, security = fields[0], fields[1], fields[2]
        if not ssid:
            continue
        try:
            signal = int(signal_str)
        except ValueError:
            continue
        secured = bool(security)
        existing = best_by_ssid.get(ssid)
        if existing is None or signal > existing.signal:
            best_by_ssid[ssid] = WifiNetwork(ssid=ssid, signal=signal, secured=secured)

    return sorted(best_by_ssid.values(), key=lambda n: n.signal, reverse=True)


def connect(ssid: str, password: str | None = None, timeout: float = 30) -> None:
    args = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise WifiError("connection attempt timed out") from e
    if result.returncode != 0:
        detail = result.stderr.strip()
        if password:
            detail = detail.replace(password, "***")
        raise WifiError(detail or "failed to connect")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_wifi.py -v`
Expected: 12 passed at this point in the plan as originally written. The real count after all four review rounds is 16 (4 more tests added for the exception-chain and missing-binary fixes described in the correction note above) — expect 16, not 12, if following the actual repo state rather than this historical step-by-step.

- [ ] **Step 5: Commit**

```bash
git add src/mtgkiosk/wifi.py tests/test_wifi.py
git commit -m "Add wifi scan/connect module wrapping nmcli"
```

---

## Task 2: Wire Wifi Into the FastAPI Backend

**Files:**
- Modify: `src/mtgkiosk/app.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests — add to `tests/test_app.py`**

Add these imports near the top, alongside the existing ones:

```python
from mtgkiosk.wifi import WifiError
```

Add these tests to the end of the file:

```python
def test_wifi_scan_returns_networks(monkeypatch):
    monkeypatch.setattr(app_module, "wifi_scan", lambda: [
        __import__("mtgkiosk.wifi", fromlist=["WifiNetwork"]).WifiNetwork(ssid="Test", signal=80, secured=True)
    ])
    client = TestClient(app_module.app)
    response = client.get("/api/wifi/scan")
    assert response.status_code == 200
    assert response.json() == [{"ssid": "Test", "signal": 80, "secured": True}]


def test_wifi_scan_returns_502_on_wifi_error(monkeypatch):
    def raise_error():
        raise WifiError("boom")
    monkeypatch.setattr(app_module, "wifi_scan", raise_error)
    client = TestClient(app_module.app)
    response = client.get("/api/wifi/scan")
    assert response.status_code == 502


def test_wifi_connect_returns_200_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "wifi_connect", lambda ssid, password: calls.append((ssid, password)))
    client = TestClient(app_module.app)
    response = client.post("/api/wifi/connect", json={"ssid": "Test", "password": "secret"})
    assert response.status_code == 200
    assert response.json() == {"connected": True}
    assert calls == [("Test", "secret")]


def test_wifi_connect_returns_502_on_wifi_error(monkeypatch):
    def raise_error(ssid, password):
        raise WifiError("boom")
    monkeypatch.setattr(app_module, "wifi_connect", raise_error)
    client = TestClient(app_module.app)
    response = client.post("/api/wifi/connect", json={"ssid": "Test", "password": "wrong"})
    assert response.status_code == 502
    assert "wrong" not in response.text
```

(`test_wifi_scan_returns_networks` uses `__import__` to reach `WifiNetwork` without a top-level import colliding with anything — simplest way to keep this addition self-contained; feel free to add a normal `from mtgkiosk.wifi import WifiNetwork` import instead if you prefer, either works.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_app.py -v`
Expected: FAIL — `AttributeError` (no `wifi_scan`/`wifi_connect` on the app module) or a 404 on the new routes

- [ ] **Step 3: Modify `src/mtgkiosk/app.py`**

Add to the imports section (alongside the existing `from .updater import ...` line):

```python
from pydantic import BaseModel

from .wifi import WifiError, connect as wifi_connect, scan as wifi_scan
```

Add this class definition anywhere before its use (e.g., right after the `app = FastAPI()` line):

```python
class WifiConnectRequest(BaseModel):
    ssid: str
    password: str | None = None
```

Add these two routes, near the other `/api/*` routes (position doesn't matter functionally, but grouping them near `get_status`/the printer routes keeps related things together):

```python
@app.get("/api/wifi/scan")
def get_wifi_scan() -> list[dict]:
    try:
        networks = wifi_scan()
    except WifiError as e:
        logger.warning("wifi scan failed: %s", e)
        raise HTTPException(status_code=502, detail="Couldn't scan for networks.") from e
    return [{"ssid": n.ssid, "signal": n.signal, "secured": n.secured} for n in networks]


@app.post("/api/wifi/connect")
def post_wifi_connect(body: WifiConnectRequest) -> dict:
    try:
        wifi_connect(body.ssid, body.password)
    except WifiError as e:
        logger.warning("wifi connect failed for ssid=%s: %s", body.ssid, e)
        raise HTTPException(status_code=502, detail="Couldn't connect. Check the password and try again.") from e
    return {"connected": True}
```

Note: `logger` already exists in this file (added during Slice 1's Task 7 review) — no new logging setup needed. Both error details are deliberately fixed, generic strings, not `str(e)` — per the design spec, this feature doesn't attempt to distinguish failure causes, and for `connect` specifically this also means a stray formatting mistake could never accidentally leak a password into an HTTP response, on top of `wifi.py`'s own scrubbing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_app.py -v`
Expected: 11 passed (7 existing + 4 new)

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: 70 passed (50 from Slice 1 + 16 from Task 1's final state, including its four review-round additions + 4 from this task)

- [ ] **Step 6: Commit**

```bash
git add src/mtgkiosk/app.py tests/test_app.py
git commit -m "Add /api/wifi/scan and /api/wifi/connect endpoints"
```

---

## Task 3: On-Screen Keyboard Component

**Files:**
- Create: `web/js/keyboard.js`

This component has no knowledge of wifi — it's a generic on-screen keyboard that writes into whatever input element last asked for it. No automated tests exist for frontend JS in this project (deliberate, no build/test tooling); verification here is a real parse check now, with full behavioral verification deferred to Task 4 once there's an actual input field to type into.

- [ ] **Step 1: Write `web/js/keyboard.js`**

```javascript
const KEYBOARD_ROWS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["shift", "z", "x", "c", "v", "b", "n", "m", "backspace"],
  ["space"],
];

let keyboardTarget = null;
let keyboardShift = false;

function buildKeyboard() {
  const container = document.getElementById("onscreen-keyboard");
  container.innerHTML = "";
  KEYBOARD_ROWS.forEach((row) => {
    const rowEl = document.createElement("div");
    rowEl.className = "keyboard-row";
    row.forEach((key) => {
      const keyEl = document.createElement("button");
      keyEl.type = "button";
      keyEl.className = "keyboard-key";
      if (key === "space") {
        keyEl.classList.add("keyboard-key-space");
        keyEl.textContent = " ";
      } else if (key === "backspace") {
        keyEl.classList.add("keyboard-key-wide");
        keyEl.textContent = "⌫";
      } else if (key === "shift") {
        keyEl.classList.add("keyboard-key-wide");
        keyEl.textContent = "⇧";
      } else {
        keyEl.textContent = key;
      }
      keyEl.addEventListener("click", () => handleKeyboardKey(key));
      rowEl.appendChild(keyEl);
    });
    container.appendChild(rowEl);
  });
}

function handleKeyboardKey(key) {
  if (!keyboardTarget) return;
  if (key === "shift") {
    keyboardShift = !keyboardShift;
    return;
  }
  if (key === "backspace") {
    keyboardTarget.value = keyboardTarget.value.slice(0, -1);
  } else if (key === "space") {
    keyboardTarget.value += " ";
  } else {
    keyboardTarget.value += keyboardShift ? key.toUpperCase() : key;
    keyboardShift = false;
  }
  keyboardTarget.dispatchEvent(new Event("input"));
}

function showKeyboardFor(inputEl) {
  keyboardTarget = inputEl;
  document.getElementById("onscreen-keyboard").classList.remove("hidden");
}

function hideKeyboard() {
  keyboardTarget = null;
  document.getElementById("onscreen-keyboard").classList.add("hidden");
}

buildKeyboard();
```

- [ ] **Step 2: Add the keyboard's container element and script tag to `web/index.html`**

Add this element right before the closing `</body>` tag, after the existing `random-card-fab` button and before the `<script src="/js/app.js">` line:

```html
<div id="onscreen-keyboard" class="keyboard hidden"></div>

<script src="/js/keyboard.js"></script>
```

(`keyboard.js` must load before `app.js`, since Task 4's wifi code in `app.js` calls `showKeyboardFor`/`hideKeyboard`, which this file defines as plain global functions — same no-module, script-order convention already used for `app.js` itself.)

- [ ] **Step 3: Add keyboard CSS to `web/css/style.css`**

```css
.keyboard {
  position: fixed;
  bottom: 0;
  left: 0;
  width: 800px;
  background: var(--surface);
  padding: 8px;
  box-sizing: border-box;
}

.keyboard-row {
  display: flex;
  justify-content: center;
  gap: 4px;
  margin-bottom: 4px;
}

.keyboard-key {
  flex: 1;
  max-width: 60px;
  height: 34px;
  background: var(--bg);
  color: var(--text);
  border: none;
  border-radius: 4px;
  font-size: 14px;
}

.keyboard-key-wide {
  max-width: 90px;
}

.keyboard-key-space {
  flex: 4;
  max-width: none;
}
```

- [ ] **Step 4: Verify the JS parses correctly**

Run: `node --check web/js/keyboard.js`
Expected: exit code 0, no output (matches how Task 8 verified `app.js` — a real parse check, not a manual read-through)

If `node` isn't available on this machine, open `web/index.html` in a browser after Task 4 is done (there's nothing to visually check yet without a real input field) and confirm the browser console shows no syntax errors on page load.

- [ ] **Step 5: Commit**

```bash
git add web/js/keyboard.js web/index.html web/css/style.css
git commit -m "Add reusable on-screen keyboard component"
```

---

## Task 4: Wifi Settings View

**Files:**
- Modify: `web/index.html`
- Modify: `web/js/app.js`
- Modify: `web/css/style.css`

- [ ] **Step 1: Add the "Connect to wifi network" button to the Settings view in `web/index.html`**

Find the existing Settings view's button row (inside `.settings-scroll`, after the `update-apply-button`):

```html
      <button id="update-check-button">Check for updates</button>
      <p id="update-status"></p>
      <button id="update-apply-button" class="hidden">Install update &amp; restart</button>
    </div>
```

Add a new button right after `update-apply-button`, still inside `.settings-scroll`:

```html
      <button id="update-check-button">Check for updates</button>
      <p id="update-status"></p>
      <button id="update-apply-button" class="hidden">Install update &amp; restart</button>

      <hr>

      <button id="wifi-settings-button">Connect to wifi network</button>
    </div>
```

- [ ] **Step 2: Add the `view-wifi` markup to `web/index.html`**

Add this new `<main>` block after the existing `view-settings` block (before the `random-card-fab` button):

```html
  <main id="view-wifi" class="view hidden">
    <div class="settings-scroll">
      <h2>Connect to Wifi</h2>
      <p id="wifi-scan-status"></p>
      <div id="wifi-network-list" class="wifi-network-list"></div>

      <div id="wifi-connect-form" class="hidden">
        <p id="wifi-selected-ssid"></p>
        <div id="wifi-password-row" class="hidden">
          <input type="text" id="wifi-password-input" placeholder="Password">
          <button type="button" id="wifi-password-toggle">Hide</button>
        </div>
        <button id="wifi-connect-button">Connect</button>
        <button id="wifi-cancel-button">Cancel</button>
      </div>
      <p id="wifi-connect-status"></p>
    </div>

    <button class="back-button" data-view="settings">Back</button>
  </main>
```

(`data-view="settings"`, not `"menu"` like every other view's Back button — this is the one view only ever reached from Settings, and it should return there, not to the main menu. `showView()` already handles this generically since it just reads whatever view name is in the `data-view` attribute.)

- [ ] **Step 3: Add wifi view CSS to `web/css/style.css`**

```css
.wifi-network-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
}

.wifi-network-item {
  text-align: left;
  padding: 10px 14px;
  background: var(--surface);
  color: var(--text);
  border: none;
  border-radius: 8px;
  font-size: 16px;
}

#wifi-password-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 10px 0;
}

#wifi-password-input {
  flex: 1;
  padding: 10px;
  font-size: 16px;
  border-radius: 8px;
  border: none;
}
```

- [ ] **Step 4: Add the wifi view logic to `web/js/app.js`**

Add this to the end of the file:

```javascript
let wifiSelectedNetwork = null;

document.getElementById("wifi-settings-button").addEventListener("click", () => {
  showView("wifi");
  loadWifiNetworks();
});

async function loadWifiNetworks() {
  const statusEl = document.getElementById("wifi-scan-status");
  const listEl = document.getElementById("wifi-network-list");
  document.getElementById("wifi-connect-form").classList.add("hidden");
  document.getElementById("wifi-connect-status").textContent = "";
  hideKeyboard();
  statusEl.textContent = "Scanning…";
  listEl.innerHTML = "";
  try {
    const response = await fetch("/api/wifi/scan");
    if (!response.ok) {
      statusEl.textContent = "Couldn't scan for networks.";
      return;
    }
    const networks = await response.json();
    if (networks.length === 0) {
      statusEl.textContent = "No networks found.";
      return;
    }
    statusEl.textContent = "";
    networks.forEach((network) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "wifi-network-item";
      item.textContent = (network.secured ? "🔒 " : "") + network.ssid;
      item.addEventListener("click", () => selectWifiNetwork(network));
      listEl.appendChild(item);
    });
  } catch (err) {
    statusEl.textContent = "Couldn't scan for networks.";
  }
}

function selectWifiNetwork(network) {
  wifiSelectedNetwork = network;
  document.getElementById("wifi-selected-ssid").textContent = network.ssid;
  document.getElementById("wifi-connect-form").classList.remove("hidden");
  document.getElementById("wifi-connect-status").textContent = "";
  const passwordRow = document.getElementById("wifi-password-row");
  const passwordInput = document.getElementById("wifi-password-input");
  passwordInput.value = "";
  if (network.secured) {
    passwordRow.classList.remove("hidden");
    showKeyboardFor(passwordInput);
  } else {
    passwordRow.classList.add("hidden");
    hideKeyboard();
  }
}

document.getElementById("wifi-password-toggle").addEventListener("click", (event) => {
  const input = document.getElementById("wifi-password-input");
  const masked = input.type === "password";
  input.type = masked ? "text" : "password";
  event.currentTarget.textContent = masked ? "Hide" : "Show";
});

document.getElementById("wifi-cancel-button").addEventListener("click", () => {
  wifiSelectedNetwork = null;
  document.getElementById("wifi-connect-form").classList.add("hidden");
  hideKeyboard();
});

document.getElementById("wifi-connect-button").addEventListener("click", async (event) => {
  if (!wifiSelectedNetwork) return;
  const button = event.currentTarget;
  const statusEl = document.getElementById("wifi-connect-status");
  const passwordInput = document.getElementById("wifi-password-input");
  button.disabled = true;
  statusEl.textContent = "Connecting…";
  try {
    const response = await fetch("/api/wifi/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ssid: wifiSelectedNetwork.ssid,
        password: wifiSelectedNetwork.secured ? passwordInput.value : null,
      }),
    });
    if (response.ok) {
      statusEl.textContent = "Connected!";
      hideKeyboard();
    } else {
      const data = await response.json().catch(() => ({}));
      statusEl.textContent = firstLine(data.detail || "Couldn't connect. Check the password and try again.");
    }
  } catch (err) {
    statusEl.textContent = "Couldn't connect: " + firstLine(err.message);
  } finally {
    button.disabled = false;
  }
});
```

(`firstLine` already exists in this file from Slice 1's Task 8 — reused here rather than duplicated.)

- [ ] **Step 5: Verify the JS parses correctly**

Run: `node --check web/js/app.js`
Expected: exit code 0, no output

- [ ] **Step 6: Manual verification in a desktop browser**

This machine has no `nmcli`, so `/api/wifi/scan` will fail here — that's expected, not a bug. Start the server and confirm the parts that don't need real wifi hardware:

Run:
```bash
.venv/Scripts/uvicorn mtgkiosk.app:app --app-dir src --port 8080
```

Open `http://127.0.0.1:8080`, go to Settings, tap "Connect to wifi network." Check by hand:
- The view shows "Couldn't scan for networks." (expected here — no `nmcli` on this machine) without crashing or hanging
- The Back button returns to Settings, not the main menu
- Tapping Back and re-entering re-triggers a scan (confirms the click handler on `wifi-settings-button` fires `loadWifiNetworks()` every time, not just once)

To verify the keyboard and connect-form UI without real hardware, temporarily test by hand in the browser console (not a permanent code change):
```javascript
selectWifiNetwork({ssid: "Test Network", signal: 80, secured: true})
```
Confirm: the password field and keyboard both appear, tapping keyboard keys types into the password field, the "Hide"/"Show" toggle correctly switches the field between masked and visible, and "Cancel" hides the form and keyboard and returns to a clean network-list state.

- [ ] **Step 7: Commit**

```bash
git add web/index.html web/js/app.js web/css/style.css
git commit -m "Add wifi settings view: scan, select, and connect flow"
```

---

## Task 5: Ship to the Real Pi and Verify Against Real Hardware

**Files:** none — this deploys through the update mechanism built in Slice 1 and verifies on the physical device via the VNC session (same constraint as before: direct SSH from the development machine doesn't work).

This task exists specifically to test the one thing Tasks 1-4 couldn't: whether `nmcli device wifi connect` genuinely works for the `admin` user without hitting a permission wall, per the open question in the design spec's Background section. Scanning was already confirmed unprivileged; connecting has not been.

- [ ] **Step 1: Push to the real remote**

From the development machine:
```bash
gh auth switch --hostname github.com --user D-lougheed
```
```bash
git push origin master
```
```bash
gh auth switch --hostname github.com --user Dlougheed
```

(The account-switching bracket is required — `gh`'s credential helper serves whichever account is globally active, not whichever owns the repo being pushed to. See the Slice 1 plan's Task 10 section for the full explanation.)

- [ ] **Step 2: Pull the update onto the Pi through the app itself**

In the Pi's touchscreen (or VNC): Settings → "Check for updates." Expected: shows "N commit(s) behind" and reveals "Install update & restart." Tap it.

This is the real end-to-end test of the update mechanism's `PartOf=mtgkiosk.service` fix from Slice 1's Task 9 — confirm the screen actually shows the new "Connect to wifi network" button after the restart, not just that the API reconnects.

- [ ] **Step 3: Verify a real scan on the physical hardware**

Tap "Connect to wifi network." Expected: a real list of nearby networks appears (compare against what `nmcli device wifi list` showed directly in the terminal earlier in this project — should roughly match).

- [ ] **Step 4: Verify a real connect**

Pick a real network (ideally the one already in use, to minimize risk of actually losing connectivity if something goes wrong), enter its real password via the on-screen keyboard, tap Connect.

Expected: "Connected!" appears, and `nmcli -t -f STATE general` (or the Settings wifi-status field, once you navigate back) confirms the connection.

If this fails with what looks like a permission error rather than a wifi error (check `journalctl -u mtgkiosk -n 50 --no-pager` for anything mentioning "not authorized" or "permission denied" from nmcli/polkit), the `netdev`-group theory from the design spec was wrong, and a privileged-helper mechanism becomes necessary — that would be new scope, not a bug in this plan's code, and should be brought back for its own brainstorming pass rather than patched ad hoc.

- [ ] **Step 5: Verify a real failure path**

Attempt to connect to a secured network using a deliberately wrong password. Expected: "Couldn't connect. Check the password and try again." — not a hang, not a crash, not the raw nmcli error text.

*(No commit step from this task on the development machine unless Step 4 surfaces a real bug needing a fix — if so, use a real commit message describing what was found, same convention as Slice 1's Task 11.)*

---

## Self-Review

**Spec coverage:**
- Goal 1 (scan, show strongest signal first) → Task 1 (`scan()`'s sort), Task 4 (renders the sorted list as-is)
- Goal 2 (tap network, password on in-page keyboard, connect) → Task 3 (keyboard), Task 4 (`selectWifiNetwork`/connect flow)
- Goal 3 (plain success/failure, no cause-parsing) → Task 1 (`connect()` never returns a cause), Task 2 (fixed generic HTTP error details)
- Non-goal: no saved-network management → no task adds it
- Non-goal: no failure-cause distinction → confirmed above
- Key decision: in-page keyboard, not matchbox-keyboard → Task 3
- Key decision: password field visible by default → Task 4 Step 2 (`type="text"`, not `type="password"`)
- Key decision: de-duplicate scan by SSID, strongest signal → Task 1 (`best_by_ssid` logic + `test_scan_deduplicates_by_ssid_keeping_strongest_signal`)
- Error handling: never crash on a wifi problem → Task 1 (`WifiError` wraps every failure path), Task 2 (caught at the API boundary)
- Empty scan result shows "No networks found" → Task 4 Step 4 (`loadWifiNetworks`)
- Testing: unit tests for scan/connect logic, manual for the view → Task 1 (11 tests), Task 4 Step 6 (manual)
- Real-hardware confirmation of the `netdev` group theory → Task 5

**Placeholder scan:** none found — every step has complete, real code or an exact command with expected output. Fixed two issues on this pass: Task 2's expected test counts were hand-waved ("minus the 4 double-counted... exact count isn't load-bearing") rather than computed — now precise (verified against the actual current repo state: `test_app.py` has 7 tests today, the full suite has 50), and Task 4 Step 2 originally walked through a wrong `data-view` value before correcting it, which is fine for explaining reasoning to a person but not for an instruction a subagent might copy verbatim — now shows only the correct markup, with the reasoning moved to a parenthetical note.

**Type consistency:** `WifiNetwork(ssid, signal, secured)`, `WifiError`, `scan()`, `connect(ssid, password)` are defined once in Task 1 and used with identical shape in Task 2's endpoints and Task 4's JSON handling (`{"ssid": ..., "signal": ..., "secured": ...}` matches the dataclass fields exactly). `showKeyboardFor`/`hideKeyboard` are defined once in Task 3 and called with matching signatures in Task 4.
