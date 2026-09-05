"""FastAPI application: serves the kiosk UI and exposes the printer/update API.

Binds to 127.0.0.1 only — enforced at the uvicorn invocation in
deploy/mtgkiosk.service, not here.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, cards, horde, images
from .cards import CardDatabaseError
from .horde import HordeError
from .ingest import ingest as ingest_cards
from .printer import card_label
from .printer.device import PrinterError, ThermalPrinter
from .updater import UpdateError, apply as apply_update, check as check_update
from .wifi import WifiError, connect as wifi_connect, scan as wifi_scan

logger = logging.getLogger(__name__)

REPO_DIR = Path(__file__).resolve().parents[2]
WEB_DIR = Path(__file__).resolve().parents[2] / "web"
DATA_DIR = REPO_DIR / "data"
CARDS_DB = DATA_DIR / "cards.sqlite"
IMAGE_CACHE = DATA_DIR / "images"

app = FastAPI()


@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    # Chromium's on-disk cache survives a kiosk-UI restart (it lives in
    # --user-data-dir, not memory) - without this, a self-update can leave
    # the browser silently running old JS/CSS against new backend code.
    # StaticFiles already handles conditional requests (ETag/Last-Modified),
    # so "no-cache" just forces revalidation rather than a full re-download.
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Strips only the "input" key (the raw submitted value) - added after a
    # missing-ssid request was found to echo a submitted wifi password back
    # verbatim via FastAPI's default validator-error handling. This does NOT
    # protect against a future @field_validator on a sensitive field (e.g.
    # ssid/password) whose own raised ValueError message echoes the invalid
    # value - e.g. `raise ValueError(f"got {v!r}")`. Any validator added to
    # WifiConnectRequest must keep its own error messages free of the raw
    # field value.
    sanitized_errors = [{k: v for k, v in error.items() if k != "input"} for error in exc.errors()]
    logger.info("request validation failed: %s", sanitized_errors)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(sanitized_errors)})


class WifiConnectRequest(BaseModel):
    ssid: str
    password: str | None = None


class CardPrintRequest(BaseModel):
    id: str


class HordeDeckRequest(BaseModel):
    subtype: str
    difficulty: str = "normal"


@lru_cache
def get_printer() -> ThermalPrinter:
    return ThermalPrinter()


def _commit_hash() -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_DIR), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "unknown"


def _wifi_state() -> str:
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "STATE", "general"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() or "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


@app.get("/api/status")
def get_status(printer: ThermalPrinter = Depends(get_printer)) -> dict:
    return {
        "printer_connected": printer.is_connected(),
        "commit": _commit_hash(),
        "wifi_state": _wifi_state(),
        "version": __version__,
    }


@app.post("/api/printer/selftest")
def post_printer_selftest(printer: ThermalPrinter = Depends(get_printer)) -> dict:
    try:
        printer.self_test()
    except PrinterError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"ok": True}


@app.get("/api/update/check")
def get_update_check() -> dict:
    try:
        status = check_update(REPO_DIR)
    except UpdateError as e:
        logger.warning("update check failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {
        "up_to_date": status.up_to_date,
        "local_commit": status.local_commit,
        "remote_commit": status.remote_commit,
        "commits_behind": status.commits_behind,
    }


@app.post("/api/update/apply")
def post_update_apply() -> dict:
    try:
        apply_update(REPO_DIR)
    except UpdateError as e:
        logger.warning("update apply failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e
    venv_pip = REPO_DIR / ".venv" / "bin" / "pip"
    result = subprocess.run([str(venv_pip), "install", "-r", str(REPO_DIR / "requirements.txt")])
    if result.returncode != 0:
        logger.error("pip install failed after update pull (returncode %s); aborting restart", result.returncode)
        raise HTTPException(status_code=502, detail="dependency install failed after update; restart aborted")
    # A plain (non-sudo) restart here would hit an interactive polkit prompt
    # that a detached systemd-run job can never answer - it depends on the
    # NOPASSWD sudoers rule installed by deploy/install.sh
    # (deploy/mtgkiosk-sudoers), scoped to exactly this command.
    schedule_result = subprocess.run(
        ["systemd-run", "--on-active=2", "sudo", "/usr/bin/systemctl", "restart", "mtgkiosk.service"]
    )
    if schedule_result.returncode != 0:
        logger.error(
            "failed to schedule restart (returncode %s); update pulled but service was not restarted",
            schedule_result.returncode,
        )
        raise HTTPException(
            status_code=502,
            detail="update applied but restart could not be scheduled; restart the service manually",
        )
    return {"restarting": True}


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


# Literal card routes are declared before /api/cards/{card_id} because FastAPI
# matches in declaration order - otherwise "status" and "random" would be
# captured as card ids.


# A rebuild downloads ~140 MB and takes minutes, far longer than a request can
# be held open, so it runs on a background thread and the UI polls for progress.
_ingest_state: dict = {"running": False, "stage": "", "done": 0, "total": None, "error": None}
_ingest_lock = threading.Lock()


def _run_ingest() -> None:
    def progress(stage: str, done: int, total: int | None) -> None:
        with _ingest_lock:
            _ingest_state.update(stage=stage, done=done, total=total)

    try:
        written = ingest_cards(CARDS_DB, progress)
    except Exception as e:
        # Deliberately broad: this runs on a background thread with no caller
        # to propagate to, and anything escaping here would strand running=True
        # forever, leaving the Settings screen stuck on "updating…" with no way
        # to retry short of restarting the service.
        logger.warning("card ingest failed: %s", e)
        with _ingest_lock:
            _ingest_state.update(running=False, stage="failed", error=str(e))
        return
    with _ingest_lock:
        _ingest_state.update(running=False, stage="done", done=written, error=None)


@app.get("/api/cards/status")
def get_cards_status() -> dict:
    with _ingest_lock:
        state = dict(_ingest_state)
    return {
        "available": cards.is_available(CARDS_DB),
        "count": cards.count(CARDS_DB),
        "updating": state["running"],
        "progress": (
            {"stage": state["stage"], "done": state["done"], "total": state["total"]}
            if state["running"]
            else None
        ),
        "error": state["error"],
    }


@app.post("/api/cards/update")
def post_cards_update() -> dict:
    with _ingest_lock:
        if _ingest_state["running"]:
            raise HTTPException(status_code=409, detail="an update is already running")
        _ingest_state.update(running=True, stage="starting", done=0, total=None, error=None)
    threading.Thread(target=_run_ingest, daemon=True).start()
    return {"started": True}


@app.get("/api/cards/random")
def get_cards_random() -> dict:
    try:
        return cards.random_card(CARDS_DB).to_dict()
    except CardDatabaseError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/api/cards/search")
def get_cards_search(q: str = "") -> list[dict]:
    return [card.to_dict() for card in cards.search(CARDS_DB, q)]


@app.post("/api/cards/print")
def post_cards_print(body: CardPrintRequest, printer: ThermalPrinter = Depends(get_printer)) -> dict:
    card = cards.get(CARDS_DB, body.id)
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")
    try:
        printer.print_image(card_label.render(card))
    except PrinterError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"ok": True}


@app.get("/api/horde/subtypes")
def get_horde_subtypes() -> dict:
    try:
        subtypes = horde.available_subtypes(CARDS_DB)
    except HordeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"subtypes": subtypes}


@app.post("/api/horde/deck")
def post_horde_deck(body: HordeDeckRequest) -> dict:
    try:
        deck = horde.build_deck(CARDS_DB, body.subtype, body.difficulty)
    except HordeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return deck.to_dict()


@app.get("/api/cards/{card_id}")
def get_card(card_id: str) -> dict:
    card = cards.get(CARDS_DB, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")
    return card.to_dict()


@app.get("/api/cards/{card_id}/image")
def get_card_image(card_id: str) -> FileResponse:
    card = cards.get(CARDS_DB, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")
    path = images.get_or_fetch(IMAGE_CACHE, card_id, card.image_uri)
    if path is None:
        # Offline, or the card genuinely has no art. Either way the lookup
        # screen treats a missing image as normal, so this is a 404 rather
        # than an error the UI has to explain.
        raise HTTPException(status_code=404, detail="image unavailable")
    return FileResponse(str(path), media_type="image/jpeg")


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
