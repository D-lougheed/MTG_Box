function showView(name) {
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  document.getElementById(`view-${name}`).classList.remove("hidden");
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

document.getElementById("selftest-button").addEventListener("click", async () => {
  const result = document.getElementById("selftest-result");
  result.textContent = "printing…";
  try {
    const response = await fetch("/api/printer/selftest", { method: "POST" });
    result.textContent = response.ok ? "sent" : "failed: printer not connected";
  } catch (err) {
    result.textContent = "failed: " + err.message;
  }
});

document.getElementById("update-check-button").addEventListener("click", async () => {
  const status = document.getElementById("update-status");
  const applyButton = document.getElementById("update-apply-button");
  status.textContent = "checking…";
  applyButton.classList.add("hidden");
  try {
    const response = await fetch("/api/update/check");
    const data = await response.json();
    if (data.up_to_date) {
      status.textContent = "up to date (" + data.local_commit.slice(0, 7) + ")";
    } else {
      status.textContent = data.commits_behind + " commit(s) behind";
      applyButton.classList.remove("hidden");
    }
  } catch (err) {
    status.textContent = "check failed: " + err.message;
  }
});

document.getElementById("update-apply-button").addEventListener("click", async () => {
  const status = document.getElementById("update-status");
  status.textContent = "updating, restarting shortly…";
  await fetch("/api/update/apply", { method: "POST" });
});
