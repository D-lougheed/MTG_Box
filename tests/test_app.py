from fastapi.testclient import TestClient

import mtgkiosk.app as app_module
from mtgkiosk.app import app, get_printer
from mtgkiosk.printer.device import PrinterError
from mtgkiosk.wifi import WifiError


class FakePrinter:
    def __init__(self, connected: bool = True, fail_selftest: bool = False):
        self.connected = connected
        self.fail_selftest = fail_selftest

    def is_connected(self) -> bool:
        return self.connected

    def self_test(self) -> None:
        if self.fail_selftest:
            raise PrinterError("no printer")


def test_status_reports_printer_connected():
    app.dependency_overrides[get_printer] = lambda: FakePrinter(connected=True)
    client = TestClient(app)
    response = client.get("/api/status")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["printer_connected"] is True


def test_status_reports_printer_disconnected():
    app.dependency_overrides[get_printer] = lambda: FakePrinter(connected=False)
    client = TestClient(app)
    response = client.get("/api/status")
    app.dependency_overrides.clear()
    assert response.json()["printer_connected"] is False


def test_selftest_returns_ok_on_success():
    app.dependency_overrides[get_printer] = lambda: FakePrinter()
    client = TestClient(app)
    response = client.post("/api/printer/selftest")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_selftest_returns_503_when_printer_errors():
    app.dependency_overrides[get_printer] = lambda: FakePrinter(fail_selftest=True)
    client = TestClient(app)
    response = client.post("/api/printer/selftest")
    app.dependency_overrides.clear()
    assert response.status_code == 503


def test_update_check_returns_502_on_git_error(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "REPO_DIR", tmp_path)
    client = TestClient(app_module.app)
    response = client.get("/api/update/check")
    assert response.status_code == 502


def test_update_apply_returns_502_on_git_error(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "REPO_DIR", tmp_path)
    client = TestClient(app_module.app)
    response = client.post("/api/update/apply")
    assert response.status_code == 502


def test_update_apply_returns_502_and_skips_restart_when_pip_install_fails(monkeypatch):
    monkeypatch.setattr(app_module, "apply_update", lambda repo_dir: None)

    calls = []

    class FakeResult:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(args, *a, **kw):
        calls.append(args)
        if "install" in args:
            return FakeResult(returncode=1)
        return FakeResult(returncode=0)

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)

    client = TestClient(app_module.app)
    response = client.post("/api/update/apply")

    assert response.status_code == 502
    assert not any("systemctl" in str(c) for c in calls)


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


def test_wifi_connect_validation_error_does_not_echo_password():
    client = TestClient(app_module.app)
    response = client.post("/api/wifi/connect", json={"password": "hunter2-super-secret"})
    assert response.status_code == 422
    assert "hunter2-super-secret" not in response.text
