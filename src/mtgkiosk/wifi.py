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
