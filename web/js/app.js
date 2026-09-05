// Each feature script owns one view and may expose a hook that runs when that
// view becomes visible. Looked up by name at call time rather than wired
// directly, so a feature script that fails to load can't stop the rest of the
// menu from working - on a kiosk, a broken sub-screen must not cost you the
// life counter mid-game.
const VIEW_HOOKS = {
  "settings": "onSettingsShown",
  "life-counter": "onLifeCounterShown",
  "random-card": "onRandomCardShown",
  "card-lookup": "onCardLookupShown",
  "horde-mode": "onHordeShown",
};

// The matching teardown hook, run on the view being left. A feature can own
// state that outlives its own screen - a press-and-hold repeat timer, an
// in-flight fetch that will touch the shared on-screen keyboard - and only the
// shell knows when the view goes away. Both have caused real bugs: a horde
// repeat timer kept draining life into the *next* game, and a slow lookup
// response reopened the keyboard on top of the life counter, burying six of
// its thirteen controls with no way out.
const VIEW_HIDDEN_HOOKS = {
  "life-counter": "onLifeCounterHidden",
  "random-card": "onRandomCardHidden",
  "card-lookup": "onCardLookupHidden",
  "horde-mode": "onHordeHidden",
};

let currentView = "menu";

function callViewHook(hookName) {
  if (!hookName || typeof window[hookName] !== "function") return;
  try {
    // Only guards synchronous throws. A hook that returns a promise is on its
    // own after the first await, so hooks must not rely on this to swallow
    // async failures.
    window[hookName]();
  } catch (err) {
    console.error(`${hookName} failed`, err);
  }
}

// The dice button is fixed bottom-right, which on the game screens sits over a
// real control - the corner player's +1 zone in the life counter, the right end
// of horde mode's Horde turn button, the loyalty badge on a looked-up card.
// Hidden centrally rather than by each feature's CSS, so it can't depend on
// element order in index.html.
//
// This is load-bearing, not cosmetic: lifecounter.css and horde.css both
// dropped the gutter they were reserving for the FAB once this existed.
// Removing a view from this set puts the dice back on top of a live control.
const FAB_HIDDEN_VIEWS = new Set(["life-counter", "horde-mode", "random-card", "card-lookup"]);

function showView(name) {
  const target = document.getElementById(`view-${name}`);
  if (!target) {
    console.error(`No view for "${name}"`);
    return;
  }
  const leaving = currentView;
  hideKeyboard();
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  target.classList.remove("hidden");
  document.getElementById("random-card-fab").classList.toggle("hidden", FAB_HIDDEN_VIEWS.has(name));
  currentView = name;

  // Teardown before setup, so a feature can't cancel work the incoming view
  // just started.
  if (leaving !== name) callViewHook(VIEW_HIDDEN_HOOKS[leaving]);
  callViewHook(VIEW_HOOKS[name]);
}

function isViewVisible(name) {
  const view = document.getElementById(`view-${name}`);
  return Boolean(view) && !view.classList.contains("hidden");
}

function onSettingsShown() {
  refreshCardsStatus();
}

function firstLine(text, maxLength = 80) {
  const line = String(text).split("\n")[0];
  if (line.length <= maxLength) return line;
  const headLength = 30;
  const tailLength = maxLength - headLength - 1;
  return line.slice(0, headLength) + "…" + line.slice(line.length - tailLength);
}

document.querySelectorAll("[data-view]").forEach((el) => {
  el.addEventListener("click", () => showView(el.dataset.view));
});

document.getElementById("random-card-fab").addEventListener("click", () => {
  showView("random-card");
});

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();

    const printerBadge = document.getElementById("printer-status");
    printerBadge.textContent = data.printer_connected ? "connected" : "disconnected";
    printerBadge.className = "badge " + (data.printer_connected ? "badge-ok" : "badge-bad");

    document.getElementById("wifi-status").textContent = data.wifi_state;
    document.getElementById("version-status").textContent = data.version;
    document.getElementById("commit-status").textContent = data.commit;
  } catch (err) {
    const printerBadge = document.getElementById("printer-status");
    printerBadge.textContent = "unreachable";
    printerBadge.className = "badge badge-bad";
  }
}

setInterval(refreshStatus, 5000);
refreshStatus();

// Polled faster than the 5s status loop only while an ingest is running, since
// a download-and-rebuild takes minutes and a stalled-looking progress line on a
// kiosk with no terminal is indistinguishable from a hang.
let cardsPollTimer = null;

async function refreshCardsStatus() {
  const statusEl = document.getElementById("cards-status");
  const button = document.getElementById("cards-update-button");
  try {
    const response = await fetch("/api/cards/status");
    const data = await response.json();

    if (data.updating) {
      const done = data.progress ? data.progress.done : 0;
      statusEl.textContent = "updating… " + done.toLocaleString() + " cards";
      button.disabled = true;
      if (cardsPollTimer === null) cardsPollTimer = setInterval(refreshCardsStatus, 1500);
      return;
    }

    if (cardsPollTimer !== null) {
      clearInterval(cardsPollTimer);
      cardsPollTimer = null;
    }
    button.disabled = false;
    statusEl.textContent = data.available ? data.count.toLocaleString() + " cards" : "not downloaded";
    button.textContent = data.available ? "Update card database" : "Download card database";
    renderImagesStatus(data.images);
    if (data.error) {
      document.getElementById("cards-update-status").textContent = "last update failed: " + firstLine(data.error);
    }
  } catch (err) {
    statusEl.textContent = "unknown";
  }
}

// Downloading every card image is ~69k requests over roughly two and a half
// hours, so it reports a real count and offers a way out. It resumes where it
// left off, which is why stopping is safe rather than destructive.
function renderImagesStatus(images) {
  const statusEl = document.getElementById("images-status");
  const startButton = document.getElementById("images-prefetch-button");
  const stopButton = document.getElementById("images-stop-button");
  const noteEl = document.getElementById("images-prefetch-status");
  if (!images) {
    statusEl.textContent = "unknown";
    return;
  }

  const progress = images.progress;
  startButton.classList.toggle("hidden", images.running);
  stopButton.classList.toggle("hidden", !images.running);
  stopButton.disabled = images.stopping;

  if (images.running && progress && progress.total) {
    const percent = Math.floor((progress.done / progress.total) * 100);
    statusEl.textContent = `${progress.done.toLocaleString()} / ${progress.total.toLocaleString()} (${percent}%)`;
    noteEl.textContent = images.stopping
      ? "stopping…"
      : `${progress.downloaded.toLocaleString()} downloaded, ${progress.skipped.toLocaleString()} already had, ${progress.failed.toLocaleString()} failed`;
    if (cardsPollTimer === null) cardsPollTimer = setInterval(refreshCardsStatus, 1500);
    return;
  }

  if (images.running) {
    statusEl.textContent = "starting…";
    if (cardsPollTimer === null) cardsPollTimer = setInterval(refreshCardsStatus, 1500);
    return;
  }

  statusEl.textContent = progress
    ? `${progress.done.toLocaleString()} of ${progress.total.toLocaleString()} cached`
    : "on demand";
  noteEl.textContent = images.error ? "last run failed: " + firstLine(images.error) : "";
}

document.getElementById("images-prefetch-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const note = document.getElementById("images-prefetch-status");
  button.disabled = true;
  note.textContent = "starting…";
  try {
    const response = await fetch("/api/cards/prefetch", { method: "POST" });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      note.textContent = "couldn't start: " + firstLine(data.detail || response.status);
      button.disabled = false;
      return;
    }
    note.textContent = "downloading — this takes a couple of hours, and resumes if interrupted";
    refreshCardsStatus();
  } catch (err) {
    note.textContent = "couldn't start: " + firstLine(err.message);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("images-stop-button").addEventListener("click", async (event) => {
  event.currentTarget.disabled = true;
  try {
    await fetch("/api/cards/prefetch/stop", { method: "POST" });
  } catch (err) {
    // The poll below reports the real state either way.
  }
  refreshCardsStatus();
});

document.getElementById("cards-update-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const status = document.getElementById("cards-update-status");
  button.disabled = true;
  status.textContent = "starting…";
  try {
    const response = await fetch("/api/cards/update", { method: "POST" });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      status.textContent = "update failed: " + firstLine(data.detail || response.status);
      button.disabled = false;
      return;
    }
    status.textContent = "downloading from Scryfall, this takes a few minutes…";
    refreshCardsStatus();
  } catch (err) {
    status.textContent = "update failed: " + firstLine(err.message);
    button.disabled = false;
  }
});

document.getElementById("selftest-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const result = document.getElementById("selftest-result");
  button.disabled = true;
  result.textContent = "printing…";
  try {
    const response = await fetch("/api/printer/selftest", { method: "POST" });
    if (response.ok) {
      result.textContent = "sent";
    } else {
      const data = await response.json().catch(() => ({}));
      result.textContent = "failed: " + (data.detail ? firstLine(data.detail) : "printer not connected");
    }
  } catch (err) {
    result.textContent = "failed: " + firstLine(err.message);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("update-check-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const status = document.getElementById("update-status");
  const applyButton = document.getElementById("update-apply-button");
  button.disabled = true;
  status.textContent = "checking…";
  applyButton.classList.add("hidden");
  try {
    const response = await fetch("/api/update/check");
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      status.textContent = "check failed: " + firstLine(data.detail || response.status);
      return;
    }
    const data = await response.json();
    if (data.up_to_date) {
      status.textContent = "up to date (" + data.local_commit.slice(0, 7) + ")";
    } else {
      status.textContent = data.commits_behind + " commit(s) behind";
      applyButton.classList.remove("hidden");
    }
  } catch (err) {
    status.textContent = "check failed: " + firstLine(err.message);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("update-apply-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const status = document.getElementById("update-status");
  button.disabled = true;
  status.textContent = "updating, restarting shortly…";
  try {
    const response = await fetch("/api/update/apply", { method: "POST" });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      status.textContent = "update failed: " + firstLine(data.detail || response.status);
      button.disabled = false;
      return;
    }
    button.classList.add("hidden");
  } catch (err) {
    status.textContent = "update failed: " + firstLine(err.message);
    button.disabled = false;
  }
});

let wifiSelectedNetwork = null;
let wifiManualToken = 0;

// Both password rows are reused across selections, so the masked state and the
// toggle's label have to be reset every time a row is freshly shown. Without
// this, tapping "Hide" once leaves every subsequent network's password field
// masked, contradicting the design decision that it defaults to visible.
function resetPasswordVisibility(input, toggle) {
  input.type = "text";
  toggle.textContent = "Hide";
}

document.getElementById("wifi-settings-button").addEventListener("click", () => {
  showView("wifi");
  loadWifiNetworks();
});

async function loadWifiNetworks() {
  const statusEl = document.getElementById("wifi-scan-status");
  const listEl = document.getElementById("wifi-network-list");
  wifiSelectedNetwork = null;
  wifiManualToken += 1;
  document.getElementById("wifi-connect-form").classList.add("hidden");
  document.getElementById("wifi-manual-form").classList.add("hidden");
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
  wifiManualToken += 1;
  document.getElementById("wifi-manual-form").classList.add("hidden");
  document.getElementById("wifi-connect-button").disabled = false;
  document.getElementById("wifi-selected-ssid").textContent = network.ssid;
  document.getElementById("wifi-connect-form").classList.remove("hidden");
  document.getElementById("wifi-connect-status").textContent = "";
  const passwordRow = document.getElementById("wifi-password-row");
  const passwordInput = document.getElementById("wifi-password-input");
  passwordInput.value = "";
  resetPasswordVisibility(passwordInput, document.getElementById("wifi-password-toggle"));
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
  document.getElementById("wifi-connect-status").textContent = "";
  hideKeyboard();
});

document.getElementById("wifi-connect-button").addEventListener("click", async (event) => {
  if (!wifiSelectedNetwork) return;
  const network = wifiSelectedNetwork;
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
        ssid: network.ssid,
        password: network.secured ? passwordInput.value : null,
      }),
    });
    if (wifiSelectedNetwork !== network) return;
    if (response.ok) {
      statusEl.textContent = "Connected!";
      hideKeyboard();
    } else {
      const data = await response.json().catch(() => ({}));
      if (wifiSelectedNetwork !== network) return;
      statusEl.textContent = firstLine(data.detail || "Couldn't connect. Check the password and try again.");
    }
  } catch (err) {
    if (wifiSelectedNetwork !== network) return;
    statusEl.textContent = "Couldn't connect: " + firstLine(err.message);
  } finally {
    if (wifiSelectedNetwork === network) button.disabled = false;
  }
});

document.getElementById("wifi-manual-button").addEventListener("click", () => {
  wifiSelectedNetwork = null;
  wifiManualToken += 1;
  document.getElementById("wifi-connect-form").classList.add("hidden");
  document.getElementById("wifi-connect-status").textContent = "";
  const ssidInput = document.getElementById("wifi-manual-ssid-input");
  const securedCheckbox = document.getElementById("wifi-manual-secured-checkbox");
  const passwordInput = document.getElementById("wifi-manual-password-input");
  ssidInput.value = "";
  securedCheckbox.checked = false;
  passwordInput.value = "";
  resetPasswordVisibility(passwordInput, document.getElementById("wifi-manual-password-toggle"));
  document.getElementById("wifi-manual-password-row").classList.add("hidden");
  document.getElementById("wifi-manual-connect-button").disabled = true;
  document.getElementById("wifi-manual-form").classList.remove("hidden");
  showKeyboardFor(ssidInput);
});

document.getElementById("wifi-manual-ssid-input").addEventListener("input", (event) => {
  document.getElementById("wifi-manual-connect-button").disabled = event.currentTarget.value.trim().length === 0;
});

document.getElementById("wifi-manual-secured-checkbox").addEventListener("change", (event) => {
  const passwordRow = document.getElementById("wifi-manual-password-row");
  const passwordInput = document.getElementById("wifi-manual-password-input");
  passwordInput.value = "";
  resetPasswordVisibility(passwordInput, document.getElementById("wifi-manual-password-toggle"));
  if (event.currentTarget.checked) {
    passwordRow.classList.remove("hidden");
    showKeyboardFor(passwordInput);
  } else {
    passwordRow.classList.add("hidden");
    showKeyboardFor(document.getElementById("wifi-manual-ssid-input"));
  }
});

document.getElementById("wifi-manual-password-toggle").addEventListener("click", (event) => {
  const input = document.getElementById("wifi-manual-password-input");
  const masked = input.type === "password";
  input.type = masked ? "text" : "password";
  event.currentTarget.textContent = masked ? "Hide" : "Show";
});

document.getElementById("wifi-manual-cancel-button").addEventListener("click", () => {
  wifiManualToken += 1;
  document.getElementById("wifi-manual-form").classList.add("hidden");
  document.getElementById("wifi-connect-status").textContent = "";
  hideKeyboard();
});

document.getElementById("wifi-manual-connect-button").addEventListener("click", async (event) => {
  const token = wifiManualToken;
  const button = event.currentTarget;
  const statusEl = document.getElementById("wifi-connect-status");
  const ssidInput = document.getElementById("wifi-manual-ssid-input");
  const securedCheckbox = document.getElementById("wifi-manual-secured-checkbox");
  const passwordInput = document.getElementById("wifi-manual-password-input");
  const ssid = ssidInput.value.trim();
  if (!ssid) return;
  const password = securedCheckbox.checked ? passwordInput.value : null;
  button.disabled = true;
  statusEl.textContent = "Connecting…";
  try {
    const response = await fetch("/api/wifi/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ssid, password }),
    });
    if (wifiManualToken !== token) return;
    if (response.ok) {
      statusEl.textContent = "Connected!";
      hideKeyboard();
    } else {
      const data = await response.json().catch(() => ({}));
      if (wifiManualToken !== token) return;
      statusEl.textContent = firstLine(data.detail || "Couldn't connect. Check the details and try again.");
    }
  } catch (err) {
    if (wifiManualToken !== token) return;
    statusEl.textContent = "Couldn't connect: " + firstLine(err.message);
  } finally {
    if (wifiManualToken === token) button.disabled = false;
  }
});
