"""Wifi scan/connect via nmcli.

connect() scrubs the password out of the rendered error message and the
exception chain before raising - unlike updater.py's credential scrubbing
(which has to guess at credential shapes in arbitrary text), this function
receives the exact secret value as a parameter, so this is a complete fix
for those two surfaces specifically. It does NOT prevent the password from
appearing in this frame's own local variables if something captures those
directly (e.g. traceback.TracebackException(capture_locals=True), which
some structured-logging/error-tracking tools do by default) - that's an
inherent property of a function that needs the plaintext password as an
argument to do its job, not something scrubbing after the fact can close.
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
    # a SSID ending in one or more literal backslashes right before the
    # delimiter can still misparse, since the regex lookbehind only checks
    # the single character immediately before each colon rather than the
    # full length of any backslash run - the network silently disappears
    # from scan results rather than showing corrupted data. Not worth a
    # full character-scanner rewrite for a vanishingly rare SSID shape.
    fields = re.split(r"(?<!\\):", line)
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in fields]


def _run_nmcli(args: list[str], timeout: float, timeout_message: str) -> subprocess.CompletedProcess:
    # TimeoutExpired's raise happens AFTER this try/except fully exits, not
    # inside the except clause - that's deliberate. Raising inside an except
    # block auto-chains the caught exception via __context__, and for a
    # connect() call that TimeoutExpired carries the full nmcli argv,
    # password included, in its .cmd attribute. Raising afterward means
    # nothing is active in sys.exc_info() to auto-chain to, so __context__
    # genuinely ends up None rather than merely hidden by __suppress_context__
    # (which is all `raise ... from None` inside the except block would do).
    timed_out = False
    result = None
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    except OSError as e:
        # A missing/unreadable nmcli binary raises here with just the
        # executable name in .filename, not the full argv - no password to
        # scrub in practice, unlike the TimeoutExpired case above.
        raise WifiError(f"couldn't run nmcli: {e}") from None

    if timed_out:
        raise WifiError(timeout_message)
    return result


def scan(timeout: float = 10) -> list[WifiNetwork]:
    result = _run_nmcli(
        ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
        timeout,
        f"scan timed out after {timeout}s",
    )
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

    result = _run_nmcli(args, timeout, "connection attempt timed out")

    if result.returncode != 0:
        detail = result.stderr.strip()
        if password:
            detail = detail.replace(password, "***")
        raise WifiError(detail or "failed to connect")
