"""FastAPI application: serves the kiosk UI and exposes the printer/update API.

Binds to 127.0.0.1 only — enforced at the uvicorn invocation in
deploy/mtgkiosk.service, not here.
"""

from __future__ import annotations

import logging
import subprocess
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .printer.device import PrinterError, ThermalPrinter
from .updater import UpdateError, apply as apply_update, check as check_update
from .wifi import WifiError, connect as wifi_connect, scan as wifi_scan

logger = logging.getLogger(__name__)

REPO_DIR = Path(__file__).resolve().parents[2]
WEB_DIR = Path(__file__).resolve().parents[2] / "web"

app = FastAPI()


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
    subprocess.run(["systemd-run", "--on-active=2", "systemctl", "restart", "mtgkiosk"])
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


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
