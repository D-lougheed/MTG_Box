import threading
import time

import pytest
from fastapi.testclient import TestClient

import mtgkiosk.app as app_module
from mtgkiosk.app import app, get_printer
from mtgkiosk.printer.device import PrinterError
from mtgkiosk.wifi import WifiError


@pytest.fixture(autouse=True)
def isolate_ingest_state():
    """Stop the background ingest's module-level state leaking between tests.

    /api/cards/update mutates a module global from a daemon thread. Without
    this, a test that starts an ingest leaves running/stage/done set for
    everything after it, and the next POST can land before the previous
    thread has released the flag - taking a 409, starting no thread, and
    failing for reasons unrelated to what it was testing.

    The wait happens on the way *in* rather than on the way out, because
    monkeypatch tears down before an autouse fixture does: waiting on exit
    would race the restoration of the very globals the thread is reading.
    """
    _wait_for_idle_ingest()
    _reset_ingest_state()
    yield
    _wait_for_idle_ingest()
    _reset_ingest_state()


def _wait_for_idle_ingest(timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while app_module._ingest_state["running"] and time.monotonic() < deadline:
        time.sleep(0.01)


def _reset_ingest_state() -> None:
    app_module._ingest_state.update(
        running=False, stage="", done=0, total=None, error=None
    )


class FakePrinter:
    def __init__(self, connected: bool = True, fail_selftest: bool = False):
        self.connected = connected
        self.fail_selftest = fail_selftest

    def is_connected(self) -> bool:
        return self.connected

    def self_test(self) -> None:
        if self.fail_selftest:
            raise PrinterError("no printer")


def test_static_response_has_no_cache_header():
    client = TestClient(app)
    response = client.get("/")
    assert response.headers.get("cache-control") == "no-cache"


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


def test_update_apply_returns_200_when_pip_and_restart_succeed(monkeypatch):
    monkeypatch.setattr(app_module, "apply_update", lambda repo_dir: None)

    calls = []

    class FakeResult:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(args, *a, **kw):
        calls.append(args)
        return FakeResult(returncode=0)

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)

    client = TestClient(app_module.app)
    response = client.post("/api/update/apply")

    assert response.status_code == 200
    assert response.json() == {"restarting": True}
    assert any("systemd-run" in str(c) for c in calls)


def test_update_apply_returns_502_when_restart_scheduling_fails(monkeypatch):
    monkeypatch.setattr(app_module, "apply_update", lambda repo_dir: None)

    class FakeResult:
        def __init__(self, returncode):
            self.returncode = returncode

    def fake_run(args, *a, **kw):
        if "systemd-run" in args:
            return FakeResult(returncode=1)
        return FakeResult(returncode=0)

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)

    client = TestClient(app_module.app)
    response = client.post("/api/update/apply")

    assert response.status_code == 502


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


def _seed_cards_db(tmp_path, rows):
    """Build a minimal card database and point the app at it."""
    import sqlite3

    from mtgkiosk import cards as cards_module

    db_path = tmp_path / "cards.sqlite"
    conn = sqlite3.connect(str(db_path))
    cards_module.create_schema(conn)
    conn.executemany(
        "INSERT INTO cards (id, name, type_line, oracle_text, power, toughness, cmc,"
        " image_uri, art_crop_uri) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db_path


ART_ROWS = [
    ("id-3", "Arty Card", "Creature — Bear", "Trample.", "2", "2", 2.0,
     "https://img.test/3.jpg", "https://img.test/3-art.jpg"),
]

ZOMBIE_ROWS = [
    ("id-1", "Rotting Regisaur", "Creature — Zombie Dinosaur", "Trample.", "7", "6", 3.0, None, None),
    ("id-2", "Diregraf Ghoul", "Creature — Zombie", "Enters tapped.", "2", "2", 1.0, "https://img.test/2.jpg", None),
]


def test_cards_status_reports_unavailable_without_a_database(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", tmp_path / "missing.sqlite")
    client = TestClient(app_module.app)
    body = client.get("/api/cards/status").json()
    assert body["available"] is False
    assert body["count"] == 0
    assert body["updating"] is False


def test_cards_random_returns_503_without_a_database(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", tmp_path / "missing.sqlite")
    client = TestClient(app_module.app)
    assert client.get("/api/cards/random").status_code == 503


def test_cards_search_returns_empty_list_without_a_database(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", tmp_path / "missing.sqlite")
    client = TestClient(app_module.app)
    response = client.get("/api/cards/search", params={"q": "bolt"})
    assert response.status_code == 200
    assert response.json() == []


def test_cards_status_and_random_work_against_a_real_database(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", _seed_cards_db(tmp_path, ZOMBIE_ROWS))
    client = TestClient(app_module.app)
    status = client.get("/api/cards/status").json()
    assert status["available"] is True
    assert status["count"] == 2
    body = client.get("/api/cards/random").json()
    assert body["name"] in {"Rotting Regisaur", "Diregraf Ghoul"}
    assert "has_image" in body


def test_cards_search_ranks_prefix_matches_first(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", _seed_cards_db(tmp_path, ZOMBIE_ROWS))
    client = TestClient(app_module.app)
    names = [card["name"] for card in client.get("/api/cards/search", params={"q": "di"}).json()]
    assert names == ["Diregraf Ghoul"]


def test_get_card_returns_404_for_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", _seed_cards_db(tmp_path, ZOMBIE_ROWS))
    client = TestClient(app_module.app)
    assert client.get("/api/cards/nope").status_code == 404


def test_card_image_returns_404_when_card_has_no_image(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", _seed_cards_db(tmp_path, ZOMBIE_ROWS))
    monkeypatch.setattr(app_module, "IMAGE_CACHE", tmp_path / "images")
    client = TestClient(app_module.app)
    assert client.get("/api/cards/id-1/image").status_code == 404


def test_card_print_returns_404_for_unknown_card(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", _seed_cards_db(tmp_path, ZOMBIE_ROWS))
    client = TestClient(app_module.app)
    assert client.post("/api/cards/print", json={"id": "nope"}).status_code == 404


def test_card_print_returns_503_when_printer_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", _seed_cards_db(tmp_path, ZOMBIE_ROWS))

    class DeadPrinter:
        def print_image(self, img):
            raise PrinterError("printer not connected")

    app.dependency_overrides[get_printer] = lambda: DeadPrinter()
    client = TestClient(app_module.app)
    response = client.post("/api/cards/print", json={"id": "id-1"})
    app.dependency_overrides.clear()
    assert response.status_code == 503


def test_horde_subtypes_returns_503_without_a_database(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", tmp_path / "missing.sqlite")
    client = TestClient(app_module.app)
    assert client.get("/api/horde/subtypes").status_code == 503


def test_horde_deck_returns_503_when_subtype_pool_is_too_small(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", _seed_cards_db(tmp_path, ZOMBIE_ROWS))
    client = TestClient(app_module.app)
    response = client.post("/api/horde/deck", json={"subtype": "Zombie", "difficulty": "normal"})
    assert response.status_code == 503


def test_cards_update_starts_a_background_ingest(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", tmp_path / "cards.sqlite")
    finished = threading.Event()

    def fake_ingest(db_path, progress=None):
        if progress:
            progress("downloading", 500, None)
        finished.set()
        return 500

    monkeypatch.setattr(app_module, "ingest_cards", fake_ingest)
    client = TestClient(app_module.app)
    assert client.post("/api/cards/update").json() == {"started": True}
    assert finished.wait(timeout=5)


def test_cards_update_records_failure_instead_of_stranding_the_running_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", tmp_path / "cards.sqlite")
    attempted = threading.Event()

    def exploding_ingest(db_path, progress=None):
        attempted.set()
        raise RuntimeError("scryfall unreachable")

    monkeypatch.setattr(app_module, "ingest_cards", exploding_ingest)
    client = TestClient(app_module.app)
    client.post("/api/cards/update")
    assert attempted.wait(timeout=5)

    for _ in range(50):
        body = client.get("/api/cards/status").json()
        if not body["updating"]:
            break
        time.sleep(0.05)
    assert body["updating"] is False
    assert "scryfall unreachable" in body["error"]


def test_cards_update_does_not_strand_the_running_flag_if_the_thread_cannot_start(monkeypatch):
    """A failed Thread.start() must not leave Settings stuck on "updating".

    running=True is committed before the thread exists, so if start() raises
    there is nothing left to clear it: the status endpoint would report an
    update forever and every retry would 409, recoverable only by restarting
    the service.
    """
    def refuse_to_start(*args, **kwargs):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(app_module.threading, "Thread", refuse_to_start)
    client = TestClient(app_module.app)
    assert client.post("/api/cards/update").status_code == 503

    body = client.get("/api/cards/status").json()
    assert body["updating"] is False
    assert "can't start new thread" in body["error"]


def test_card_print_falls_back_to_text_when_art_is_unavailable(tmp_path, monkeypatch):
    """Printing must work at a table with no network and an uncached card.

    Art is a nicety; the label coming out is not. Every art failure degrades
    to the text label rather than refusing to print.
    """
    monkeypatch.setattr(app_module, "CARDS_DB", _seed_cards_db(tmp_path, ZOMBIE_ROWS))
    monkeypatch.setattr(app_module, "ART_CACHE", tmp_path / "art")
    monkeypatch.setattr(app_module.images, "get_or_fetch", lambda *a, **kw: None)

    printed = []

    class RecordingPrinter:
        def print_image(self, img):
            printed.append(img)

    app.dependency_overrides[get_printer] = lambda: RecordingPrinter()
    client = TestClient(app_module.app)
    response = client.post("/api/cards/print", json={"id": "id-2"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"ok": True, "art": False}
    assert printed and printed[0].size == (609, 406)


def test_card_print_uses_art_when_it_is_cached(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(app_module, "CARDS_DB", _seed_cards_db(tmp_path, ART_ROWS))
    art_dir = tmp_path / "art"
    art_dir.mkdir()
    art_path = art_dir / "id-3.jpg"
    Image.new("L", (626, 457), 128).save(art_path)
    monkeypatch.setattr(app_module, "ART_CACHE", art_dir)
    monkeypatch.setattr(app_module.images, "get_or_fetch", lambda *a, **kw: art_path)

    class RecordingPrinter:
        def print_image(self, img):
            pass

    app.dependency_overrides[get_printer] = lambda: RecordingPrinter()
    client = TestClient(app_module.app)
    response = client.post("/api/cards/print", json={"id": "id-3"})
    app.dependency_overrides.clear()

    assert response.json() == {"ok": True, "art": True}


def test_card_print_can_be_asked_for_text_only(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "CARDS_DB", _seed_cards_db(tmp_path, ART_ROWS))

    def explode(*a, **kw):
        raise AssertionError("art must not be fetched when the caller opted out")

    monkeypatch.setattr(app_module.images, "get_or_fetch", explode)

    class RecordingPrinter:
        def print_image(self, img):
            pass

    app.dependency_overrides[get_printer] = lambda: RecordingPrinter()
    client = TestClient(app_module.app)
    response = client.post("/api/cards/print", json={"id": "id-3", "art": False})
    app.dependency_overrides.clear()

    assert response.json() == {"ok": True, "art": False}
