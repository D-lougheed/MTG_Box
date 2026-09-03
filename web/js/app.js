function showView(name) {
  const target = document.getElementById(`view-${name}`);
  if (!target) {
    console.error(`No view for "${name}"`);
    return;
  }
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  target.classList.remove("hidden");
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
