# Slice 1: Kiosk Shell + Printer Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Raspberry Pi that boots directly into a fullscreen kiosk showing a main menu, with a fully working Settings screen (printer status, self-test print, git-based update) and a proven, unit-tested TSPL2 printer library.

**Architecture:** A FastAPI backend (`mtgkiosk` package) serves a static, build-step-free HTML/CSS/JS frontend and exposes a small JSON API. Chromium runs the frontend in kiosk mode. The printer stack is split into pure, hardware-free modules (`tspl.py`, `raster.py`) plus a thin hardware-touching `transport.py`, composed by a `device.py` facade. Both the backend and the kiosk browser run as `Restart=always` systemd units.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, Pillow, pytest. Plain HTML/CSS/JS on the frontend — no build tool, no framework. systemd for process supervision, udev for stable device naming, git for updates.

Reference: [`docs/superpowers/specs/2026-09-03-kiosk-shell-and-printer-design.md`](../specs/2026-09-03-kiosk-shell-and-printer-design.md)

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `requirements-dev.txt`
- Create: `src/mtgkiosk/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_scaffolding.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "mtgkiosk"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi",
    "uvicorn",
    "pillow",
]

[tool.setuptools.packages.find]
where = ["src"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Write `requirements-dev.txt`**

```
pytest
httpx
```

(`httpx` is required by FastAPI's `TestClient`.)

- [ ] **Step 3: Write `src/mtgkiosk/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Write `tests/__init__.py`**

Empty file.

- [ ] **Step 5: Write the first test, `tests/test_scaffolding.py`**

```python
from mtgkiosk import __version__


def test_package_is_importable_and_versioned():
    assert __version__ == "0.1.0"
```

- [ ] **Step 6: Create a virtual environment and install the package editable**

Run:
```bash
python -m venv .venv
```
```bash
.venv/Scripts/pip install -e . -r requirements-dev.txt
```
(On the Pi later, the equivalent is `.venv/bin/pip`.)

- [ ] **Step 7: Run the test and verify it passes**

Run: `.venv/Scripts/python -m pytest tests/ -v`
Expected: `test_scaffolding.py::test_package_is_importable_and_versioned PASSED`

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml requirements-dev.txt src/mtgkiosk/__init__.py tests/__init__.py tests/test_scaffolding.py
git commit -m "Scaffold mtgkiosk package with editable install and pytest"
```

---

## Task 2: TSPL2 Command Builder (`tspl.py`)

Pure functions. No I/O, no hardware. Every dimension takes an explicit unit suffix — the hardware bring-up in the spec found that this printer's ambient default unit is millimeters, and an earlier unitless `SIZE 4,6` (intended as inches) silently produced a 4mm x 6mm print area. This module never repeats that mistake: units are always written into the command string.

**Files:**
- Create: `src/mtgkiosk/printer/__init__.py`
- Create: `src/mtgkiosk/printer/tspl.py`
- Create: `tests/test_tspl.py`

- [ ] **Step 1: Create the package file**

`src/mtgkiosk/printer/__init__.py` — empty file.

- [ ] **Step 2: Write the failing tests, `tests/test_tspl.py`**

```python
from mtgkiosk.printer import tspl


def test_size_mm_formats_explicit_units():
    assert tspl.size_mm(76.2, 50.8) == b"SIZE 76.2 mm,50.8 mm\r\n"


def test_gap_mm_formats_explicit_units():
    assert tspl.gap_mm(3, 0) == b"GAP 3 mm,0 mm\r\n"


def test_gap_mm_defaults_offset_to_zero():
    assert tspl.gap_mm(3) == b"GAP 3 mm,0 mm\r\n"


def test_direction():
    assert tspl.direction(1) == b"DIRECTION 1\r\n"


def test_cls():
    assert tspl.cls() == b"CLS\r\n"


def test_text_basic():
    result = tspl.text(100, 100, "3", 0, 1, 1, "TSPL OK")
    assert result == b'TEXT 100,100,"3",0,1,1,"TSPL OK"\r\n'


def test_text_escapes_embedded_quotes():
    result = tspl.text(0, 0, "3", 0, 1, 1, 'Say "hi"')
    assert result == b'TEXT 0,0,"3",0,1,1,"Say \\"hi\\""\r\n'


def test_bitmap_embeds_raw_bytes_with_header():
    data = bytes([0xFF, 0x00, 0xFF])
    result = tspl.bitmap(10, 20, 1, 3, 0, data)
    assert result == b"BITMAP 10,20,1,3,0," + data + b"\r\n"


def test_print_label_default():
    assert tspl.print_label() == b"PRINT 1,1\r\n"


def test_print_label_explicit_counts():
    assert tspl.print_label(sets=2, copies=3) == b"PRINT 2,3\r\n"


def test_selftest():
    assert tspl.selftest() == b"SELFTEST\r\n"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_tspl.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mtgkiosk.printer'`

- [ ] **Step 4: Write `src/mtgkiosk/printer/tspl.py`**

```python
"""TSPL2 command builder. Pure functions: arguments in, bytes out. No I/O.

Every dimension is written with an explicit unit suffix. Do not add a
unitless code path — this printer's ambient default unit is millimeters,
and a unitless `SIZE 4,6` meant as inches silently produced a 4mm x 6mm
print area during hardware bring-up (see the Slice 1 design spec).
"""


def size_mm(width_mm: float, height_mm: float) -> bytes:
    return f"SIZE {width_mm} mm,{height_mm} mm\r\n".encode("ascii")


def gap_mm(gap_mm_value: float, offset_mm: float = 0) -> bytes:
    return f"GAP {gap_mm_value} mm,{offset_mm} mm\r\n".encode("ascii")


def direction(value: int) -> bytes:
    return f"DIRECTION {value}\r\n".encode("ascii")


def cls() -> bytes:
    return b"CLS\r\n"


def text(x: int, y: int, font: str, rotation: int, x_mult: int, y_mult: int, content: str) -> bytes:
    escaped = content.replace('"', '\\"')
    return f'TEXT {x},{y},"{font}",{rotation},{x_mult},{y_mult},"{escaped}"\r\n'.encode("ascii")


def bitmap(x: int, y: int, width_bytes: int, height: int, mode: int, data: bytes) -> bytes:
    header = f"BITMAP {x},{y},{width_bytes},{height},{mode},".encode("ascii")
    return header + data + b"\r\n"


def print_label(sets: int = 1, copies: int = 1) -> bytes:
    return f"PRINT {sets},{copies}\r\n".encode("ascii")


def selftest() -> bytes:
    return b"SELFTEST\r\n"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_tspl.py -v`
Expected: 11 passed

- [ ] **Step 6: Commit**

```bash
git add src/mtgkiosk/printer/__init__.py src/mtgkiosk/printer/tspl.py tests/test_tspl.py
git commit -m "Add TSPL2 command builder with explicit-unit dimensions"
```

---

## Task 3: Raster Image Packing (`raster.py`)

Converts a Pillow image into the 1-bit packed row format TSPL2's `BITMAP` command expects. Pure function, no I/O. Contract: bit `1` means "print this dot" (dark).

**Files:**
- Create: `src/mtgkiosk/printer/raster.py`
- Create: `tests/test_raster.py`

- [ ] **Step 1: Write the failing tests, `tests/test_raster.py`**

```python
from PIL import Image

from mtgkiosk.printer import raster


def test_pack_image_all_white_is_all_zero_bits():
    img = Image.new("L", (8, 2), color=255)
    width_bytes, height, data = raster.pack_image(img)
    assert (width_bytes, height) == (1, 2)
    assert data == bytes([0x00, 0x00])


def test_pack_image_all_black_is_all_one_bits():
    img = Image.new("L", (8, 2), color=0)
    width_bytes, height, data = raster.pack_image(img)
    assert (width_bytes, height) == (1, 2)
    assert data == bytes([0xFF, 0xFF])


def test_pack_image_left_half_black_right_half_white():
    img = Image.new("L", (8, 1), color=255)
    for x in range(4):
        img.putpixel((x, 0), 0)
    _, _, data = raster.pack_image(img)
    assert data == bytes([0b11110000])


def test_pack_image_pads_width_to_byte_boundary():
    img = Image.new("L", (5, 1), color=0)
    width_bytes, _, data = raster.pack_image(img)
    assert width_bytes == 1
    assert data == bytes([0b11111000])


def test_pack_image_without_dither_uses_hard_threshold():
    img = Image.new("L", (8, 1), color=127)
    _, _, data = raster.pack_image(img, dither=False)
    assert data == bytes([0xFF])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_raster.py -v`
Expected: FAIL with `AttributeError: module 'mtgkiosk.printer.raster' has no attribute 'pack_image'` (or `ModuleNotFoundError` if the file doesn't exist yet)

- [ ] **Step 3: Write `src/mtgkiosk/printer/raster.py`**

```python
"""Pillow image -> 1-bit packed rows for TSPL BITMAP. Pure function, no I/O.

Contract: a packed bit of 1 means "print this dot" (dark). Row length is
padded up to a whole byte, matching TSPL2's BITMAP row format.
"""

from PIL import Image


def pack_image(img: Image.Image, dither: bool = False) -> tuple[int, int, bytes]:
    gray = img.convert("L")
    if dither:
        bw = gray.convert("1")
    else:
        bw = gray.point(lambda p: 255 if p >= 128 else 0).convert("1")

    width, height = bw.size
    width_bytes = (width + 7) // 8
    pixels = bw.load()

    rows = bytearray()
    for y in range(height):
        row = bytearray(width_bytes)
        for x in range(width):
            if pixels[x, y] == 0:  # PIL "1" mode: 0 = black
                row[x // 8] |= 0x80 >> (x % 8)
        rows.extend(row)

    return width_bytes, height, bytes(rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_raster.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/mtgkiosk/printer/raster.py tests/test_raster.py
git commit -m "Add image-to-BITMAP raster packing"
```

---

## Task 4: Transport Abstraction (`transport.py`)

The only module allowed to touch the OS device node. Confirmed via hardware bring-up that this printer binds to the kernel's `usblp` driver, so only `UsbLpTransport` is built. The `Transport` protocol is kept narrow (`write`, `is_present`) so a second implementation could be added later without changing any caller — but none is built now (YAGNI).

**Files:**
- Create: `src/mtgkiosk/printer/transport.py`
- Create: `tests/test_transport.py`

- [ ] **Step 1: Write the failing tests, `tests/test_transport.py`**

```python
from mtgkiosk.printer.transport import UsbLpTransport


def test_is_present_false_when_path_missing(tmp_path):
    transport = UsbLpTransport(str(tmp_path / "does-not-exist"))
    assert transport.is_present() is False


def test_is_present_true_when_path_exists(tmp_path):
    device = tmp_path / "fake-printer"
    device.write_bytes(b"")
    transport = UsbLpTransport(str(device))
    assert transport.is_present() is True


def test_write_sends_exact_bytes(tmp_path):
    device = tmp_path / "fake-printer"
    device.write_bytes(b"")
    transport = UsbLpTransport(str(device))
    transport.write(b"SELFTEST\r\n")
    assert device.read_bytes() == b"SELFTEST\r\n"


def test_write_raises_when_device_missing(tmp_path):
    transport = UsbLpTransport(str(tmp_path / "does-not-exist"))
    try:
        transport.write(b"data")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_transport.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mtgkiosk.printer.transport'`

- [ ] **Step 3: Write `src/mtgkiosk/printer/transport.py`**

```python
"""Hardware I/O for the thermal printer. The only module that touches the OS device node.

Confirmed via hardware bring-up: this printer (Poskey/GEZHI M4202,
vid=0x2D37 pid=0x81F7) binds to the kernel's usblp driver, so only
UsbLpTransport is implemented. If a future printer needs raw endpoint
access instead, add a second class implementing the same Transport
protocol — do not build it speculatively now.
"""

from pathlib import Path
from typing import Protocol


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def is_present(self) -> bool: ...


class UsbLpTransport:
    def __init__(self, path: str = "/dev/mtgprinter"):
        self._path = Path(path)

    def is_present(self) -> bool:
        return self._path.exists()

    def write(self, data: bytes) -> None:
        if not self._path.exists():
            raise FileNotFoundError(str(self._path))
        with open(self._path, "wb") as f:
            f.write(data)
```

*(Correction found during implementation: a plain `open(path, "wb")` does not raise `FileNotFoundError` for a missing file when its parent directory exists — "wb" mode creates it. The explicit existence check above is required for `test_write_raises_when_device_missing` to actually pass, and is also the semantically correct behavior: writing to a missing printer device node should fail clearly, not silently create a stray regular file in its place.)*

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_transport.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/mtgkiosk/printer/transport.py tests/test_transport.py
git commit -m "Add UsbLpTransport for direct device-node writes"
```

---

## Task 5: Printer Facade (`device.py`)

The public surface the rest of the app uses. Composes `tspl`, `raster`, and a `Transport`. Owns the "a printer problem must never take down the kiosk" rule from the spec: every hardware error is caught and re-raised as `PrinterError`, never left as a raw `OSError` for a caller to mishandle.

**Files:**
- Create: `src/mtgkiosk/printer/device.py`
- Create: `tests/test_device.py`

- [ ] **Step 1: Write the failing tests, `tests/test_device.py`**

```python
import pytest
from PIL import Image

from mtgkiosk.printer.device import PrinterError, ThermalPrinter


class FakeTransport:
    def __init__(self, present: bool = True, fail: bool = False):
        self.present = present
        self.fail = fail
        self.writes: list[bytes] = []

    def is_present(self) -> bool:
        return self.present

    def write(self, data: bytes) -> None:
        if self.fail:
            raise OSError("simulated write failure")
        self.writes.append(data)


def test_is_connected_reflects_transport():
    printer = ThermalPrinter(transport=FakeTransport(present=False))
    assert printer.is_connected() is False


def test_self_test_sends_selftest_command():
    transport = FakeTransport()
    printer = ThermalPrinter(transport=transport)
    printer.self_test()
    assert transport.writes == [b"SELFTEST\r\n"]


def test_print_text_label_sends_full_command_sequence():
    transport = FakeTransport()
    printer = ThermalPrinter(transport=transport)
    printer.print_text_label(["Line One"])
    sent = transport.writes[0]
    assert sent.startswith(b"SIZE 76.2 mm,50.8 mm\r\n")
    assert b'TEXT 20,20,"3",0,1,1,"Line One"\r\n' in sent
    assert sent.endswith(b"PRINT 1,1\r\n")


def test_print_text_label_raises_printer_error_when_disconnected():
    printer = ThermalPrinter(transport=FakeTransport(present=False))
    with pytest.raises(PrinterError):
        printer.print_text_label(["hi"])


def test_print_text_label_raises_printer_error_on_write_failure():
    printer = ThermalPrinter(transport=FakeTransport(fail=True))
    with pytest.raises(PrinterError):
        printer.print_text_label(["hi"])


def test_print_image_sends_bitmap_command():
    transport = FakeTransport()
    printer = ThermalPrinter(transport=transport)
    printer.print_image(Image.new("L", (8, 8), color=255))
    sent = transport.writes[0]
    assert b"BITMAP 0,0,1,8,0," in sent
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_device.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mtgkiosk.printer.device'`

- [ ] **Step 3: Write `src/mtgkiosk/printer/device.py`**

```python
"""Public facade for the thermal printer. Composes tspl, raster, and a Transport.

Governing rule (from the Slice 1 design spec): a printer problem must
never take down the kiosk. Every hardware failure is caught here and
re-raised as PrinterError; nothing upstream ever sees a raw OSError.
"""

from __future__ import annotations

from PIL import Image

from . import raster, tspl
from .transport import Transport, UsbLpTransport

LABEL_WIDTH_MM = 76.2  # 3in
LABEL_HEIGHT_MM = 50.8  # 2in
GAP_MM = 3


class PrinterError(Exception):
    pass


class ThermalPrinter:
    def __init__(self, transport: Transport | None = None):
        self._transport = transport or UsbLpTransport()

    def is_connected(self) -> bool:
        try:
            return self._transport.is_present()
        except Exception:
            return False

    def self_test(self) -> None:
        self._send(tspl.selftest())

    def print_text_label(
        self,
        lines: list[str],
        size: tuple[float, float] = (LABEL_WIDTH_MM, LABEL_HEIGHT_MM),
    ) -> None:
        width_mm, height_mm = size
        cmd = tspl.size_mm(width_mm, height_mm)
        cmd += tspl.gap_mm(GAP_MM)
        cmd += tspl.direction(1)
        cmd += tspl.cls()
        y = 20
        for line in lines:
            cmd += tspl.text(20, y, "3", 0, 1, 1, line)
            y += 30
        cmd += tspl.print_label()
        self._send(cmd)

    def print_image(
        self,
        img: Image.Image,
        size: tuple[float, float] = (LABEL_WIDTH_MM, LABEL_HEIGHT_MM),
    ) -> None:
        width_mm, height_mm = size
        width_bytes, height, data = raster.pack_image(img)
        cmd = tspl.size_mm(width_mm, height_mm)
        cmd += tspl.gap_mm(GAP_MM)
        cmd += tspl.direction(1)
        cmd += tspl.cls()
        cmd += tspl.bitmap(0, 0, width_bytes, height, 0, data)
        cmd += tspl.print_label()
        self._send(cmd)

    def _send(self, data: bytes) -> None:
        try:
            if not self._transport.is_present():
                raise PrinterError("printer not connected")
            self._transport.write(data)
        except PrinterError:
            raise
        except Exception as e:
            raise PrinterError(f"printer error: {e}") from e
```

*(Correction found during review: the code as originally drafted only wrapped `write()` in `except OSError`, leaving `is_present()` unguarded in both `is_connected()` and `_send()`. Since `is_connected()` backs the `/api/status` endpoint the frontend polls every 5s, an unguarded exception there would 500 that endpoint instead of showing the graceful "disconnected" badge the design spec promises. Broadened to `except Exception` — with `PrinterError` re-raised first to avoid double-wrapping — so the module's own stated invariant, "a printer problem must never take down the kiosk," actually holds for any transport failure, not just `OSError` subtypes.)*

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_device.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/mtgkiosk/printer/device.py tests/test_device.py
git commit -m "Add ThermalPrinter facade with PrinterError isolation"
```

---

## Task 6: Updater (`updater.py`)

Git-based update check/apply. Tested entirely against temporary local git repositories standing in for the real GitHub remote — no network access needed.

**Files:**
- Create: `src/mtgkiosk/updater.py`
- Create: `tests/test_updater.py`

- [ ] **Step 1: Write the failing tests, `tests/test_updater.py`**

```python
import subprocess
from pathlib import Path

import pytest

from mtgkiosk.updater import UpdateError, apply, check


def _git(repo_dir: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo_dir), *args], check=True, capture_output=True)


def _init_remote_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q")
    _git(remote, "config", "user.email", "test@example.com")
    _git(remote, "config", "user.name", "Test")
    (remote / "file.txt").write_text("v1")
    _git(remote, "add", "file.txt")
    _git(remote, "commit", "-q", "-m", "initial")

    local = tmp_path / "local"
    subprocess.run(["git", "clone", "-q", str(remote), str(local)], check=True, capture_output=True)
    _git(local, "config", "user.email", "test@example.com")
    _git(local, "config", "user.name", "Test")
    return remote, local


def test_check_reports_up_to_date_immediately_after_clone(tmp_path):
    _remote, local = _init_remote_and_clone(tmp_path)
    status = check(local)
    assert status.up_to_date is True
    assert status.commits_behind == 0


def test_check_detects_new_remote_commit(tmp_path):
    remote, local = _init_remote_and_clone(tmp_path)
    (remote / "file.txt").write_text("v2")
    _git(remote, "add", "file.txt")
    _git(remote, "commit", "-q", "-m", "second")

    status = check(local)
    assert status.up_to_date is False
    assert status.commits_behind == 1


def test_apply_pulls_new_commit(tmp_path):
    remote, local = _init_remote_and_clone(tmp_path)
    (remote / "file.txt").write_text("v2")
    _git(remote, "add", "file.txt")
    _git(remote, "commit", "-q", "-m", "second")

    apply(local)
    assert (local / "file.txt").read_text() == "v2"


def test_apply_raises_on_diverged_local_history(tmp_path):
    remote, local = _init_remote_and_clone(tmp_path)
    (remote / "file.txt").write_text("v2-remote")
    _git(remote, "add", "file.txt")
    _git(remote, "commit", "-q", "-m", "remote-diverges")

    (local / "file.txt").write_text("v2-local")
    _git(local, "add", "file.txt")
    _git(local, "commit", "-q", "-m", "local-diverges")

    with pytest.raises(UpdateError):
        apply(local)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_updater.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mtgkiosk.updater'`

- [ ] **Step 3: Write `src/mtgkiosk/updater.py`**

```python
"""Git-based update mechanism: check for and apply updates from the configured remote.

Uses --ff-only on apply deliberately: a diverged local history (e.g. from
a manual edit on the Pi) fails loudly here rather than silently clobbering
whatever was there, per the Slice 1 design spec's error-handling table.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class UpdateError(Exception):
    pass


@dataclass
class UpdateStatus:
    up_to_date: bool
    local_commit: str
    remote_commit: str
    commits_behind: int


def _run(repo_dir: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise UpdateError(result.stderr.strip())
    return result.stdout.strip()


def _current_branch(repo_dir: Path) -> str:
    return _run(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")


def check(repo_dir: Path) -> UpdateStatus:
    _run(repo_dir, "fetch", "origin")
    branch = _current_branch(repo_dir)
    local_commit = _run(repo_dir, "rev-parse", "HEAD")
    remote_commit = _run(repo_dir, "rev-parse", f"origin/{branch}")
    commits_behind = int(_run(repo_dir, "rev-list", "--count", f"{local_commit}..{remote_commit}"))
    return UpdateStatus(
        up_to_date=commits_behind == 0,
        local_commit=local_commit,
        remote_commit=remote_commit,
        commits_behind=commits_behind,
    )


def apply(repo_dir: Path) -> None:
    _run(repo_dir, "pull", "--ff-only")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_updater.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/mtgkiosk/updater.py tests/test_updater.py
git commit -m "Add git-based update check/apply with ff-only safety"
```

---

## Task 7: FastAPI Backend (`app.py`)

Wires the printer and updater into the four API endpoints from the spec, plus serves `web/` as static files. Uses FastAPI's `Depends()` for the printer so tests can substitute a fake without touching real hardware.

**Files:**
- Create: `src/mtgkiosk/app.py`
- Create: `tests/test_app.py`

- [ ] **Step 1: Write the failing tests, `tests/test_app.py`**

```python
from fastapi.testclient import TestClient

import mtgkiosk.app as app_module
from mtgkiosk.app import app, get_printer
from mtgkiosk.printer.device import PrinterError


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mtgkiosk.app'`

- [ ] **Step 3: Create an empty `web/` placeholder so `StaticFiles` has a directory to mount**

Run:
```bash
mkdir -p web
```
```bash
touch web/.gitkeep
```

- [ ] **Step 4: Write `src/mtgkiosk/app.py`**

```python
"""FastAPI application: serves the kiosk UI and exposes the printer/update API.

Binds to 127.0.0.1 only — enforced at the uvicorn invocation in
deploy/mtgkiosk.service, not here.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import __version__
from .printer.device import PrinterError, ThermalPrinter
from .updater import UpdateError, apply as apply_update, check as check_update

REPO_DIR = Path(__file__).resolve().parents[2]
WEB_DIR = Path(__file__).resolve().parents[2] / "web"

app = FastAPI()


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
        raise HTTPException(status_code=502, detail=str(e)) from e
    venv_pip = REPO_DIR / ".venv" / "bin" / "pip"
    subprocess.run([str(venv_pip), "install", "-r", str(REPO_DIR / "requirements.txt")])
    subprocess.run(["systemd-run", "--on-active=2", "systemctl", "restart", "mtgkiosk"])
    return {"restarting": True}


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
```

*(Correction found during Task 6 review: the design spec's update data flow calls for "reinstall requirements if changed" between pull and restart, which the original Task 7 draft omitted entirely. Reinstalling unconditionally rather than diffing for a dependency change is a deliberate simplification — `pip install -r` is fast and idempotent when nothing changed, and detecting "did requirements.txt change" correctly (across a multi-commit pull) is meaningfully more code for a Slice 1 appliance that updates rarely.)*

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_app.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/mtgkiosk/app.py tests/test_app.py web/.gitkeep
git commit -m "Add FastAPI backend wiring printer and updater to the API"
```

---

## Task 8: Frontend Kiosk Shell (`web/`)

Plain HTML/CSS/JS, no build step, matching the design's update-mechanism-driven decision to avoid frontend tooling. Not TDD'd — there's no test runner for this by design — but each step below produces something to check by hand once Task 11 puts it on a real screen. Sized to the display's native 800x480.

**Files:**
- Create: `web/index.html`
- Create: `web/css/style.css`
- Create: `web/js/app.js`

- [ ] **Step 1: Write `web/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=800, initial-scale=1.0">
  <title>MTG Kiosk</title>
  <link rel="stylesheet" href="/css/style.css">
</head>
<body>
  <main id="view-menu" class="view">
    <h1>MTG Kiosk</h1>
    <div class="tile-grid">
      <button class="tile" data-view="life-counter">Life Counter</button>
      <button class="tile" data-view="horde-mode">Horde Mode</button>
      <button class="tile" data-view="card-lookup">Card Lookup</button>
      <button class="tile" data-view="random-card">Random Card</button>
      <button class="tile" data-view="settings">Settings</button>
    </div>
  </main>

  <main id="view-life-counter" class="view hidden">
    <p class="stub-message">Life Counter — coming in Slice 3.</p>
    <button class="back-button" data-view="menu">Back</button>
  </main>

  <main id="view-horde-mode" class="view hidden">
    <p class="stub-message">Horde Mode — coming in Slice 5.</p>
    <button class="back-button" data-view="menu">Back</button>
  </main>

  <main id="view-card-lookup" class="view hidden">
    <p class="stub-message">Card Lookup — coming in Slice 4.</p>
    <button class="back-button" data-view="menu">Back</button>
  </main>

  <main id="view-random-card" class="view hidden">
    <p class="stub-message">Random Card — coming in Slice 2.</p>
    <button class="back-button" data-view="menu">Back</button>
  </main>

  <main id="view-settings" class="view hidden">
    <h2>Settings</h2>
    <section class="status-row">
      <span>Printer:</span>
      <span id="printer-status" class="badge badge-unknown">checking…</span>
    </section>
    <section class="status-row">
      <span>Wifi:</span>
      <span id="wifi-status">checking…</span>
    </section>
    <section class="status-row">
      <span>Version:</span>
      <span id="version-status">checking…</span>
    </section>
    <section class="status-row">
      <span>Commit:</span>
      <span id="commit-status">checking…</span>
    </section>

    <button id="selftest-button">Print self-test label</button>
    <p id="selftest-result"></p>

    <hr>

    <button id="update-check-button">Check for updates</button>
    <p id="update-status"></p>
    <button id="update-apply-button" class="hidden">Install update &amp; restart</button>

    <button class="back-button" data-view="menu">Back</button>
  </main>

  <button id="random-card-fab" title="Random card">🎲</button>

  <script src="/js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `web/css/style.css`**

```css
:root {
  --bg: #14151a;
  --surface: #1f2128;
  --text: #f2f2f2;
  --muted: #9a9ca6;
  --accent: #d4a53f;
  --danger: #c0392b;
  --ok: #3fa34d;
}

* {
  box-sizing: border-box;
}

html, body {
  margin: 0;
  width: 800px;
  height: 480px;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
  overflow: hidden;
  user-select: none;
}

.view {
  width: 800px;
  height: 480px;
  padding: 24px;
  display: flex;
  flex-direction: column;
}

.hidden {
  display: none !important;
}

h1 {
  margin: 0 0 20px 0;
  font-size: 28px;
  text-align: center;
}

h2 {
  margin: 0 0 16px 0;
  font-size: 22px;
}

.tile-grid {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.tile {
  background: var(--surface);
  color: var(--text);
  border: 2px solid transparent;
  border-radius: 12px;
  font-size: 20px;
  cursor: pointer;
}

.tile:active {
  border-color: var(--accent);
}

.stub-message {
  font-size: 18px;
  color: var(--muted);
}

.back-button {
  margin-top: auto;
  align-self: flex-start;
  background: var(--surface);
  color: var(--text);
  border: none;
  border-radius: 8px;
  padding: 14px 20px;
  font-size: 16px;
}

.status-row {
  display: flex;
  justify-content: space-between;
  max-width: 400px;
  padding: 6px 0;
  font-size: 16px;
  border-bottom: 1px solid #2a2c34;
}

.badge {
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 14px;
}

.badge-ok {
  background: var(--ok);
}

.badge-bad {
  background: var(--danger);
}

.badge-unknown {
  background: #444;
}

#selftest-button, #update-check-button, #update-apply-button {
  margin-top: 16px;
  align-self: flex-start;
  padding: 14px 20px;
  font-size: 16px;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #1a1a1a;
}

#random-card-fab {
  position: fixed;
  bottom: 16px;
  right: 16px;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: none;
  background: var(--accent);
  font-size: 24px;
}
```

- [ ] **Step 3: Write `web/js/app.js`**

```javascript
function showView(name) {
  const target = document.getElementById(`view-${name}`);
  if (!target) {
    console.error(`No view for "${name}"`);
    return;
  }
  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  target.classList.remove("hidden");
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
      result.textContent = "failed: " + (data.detail || "printer not connected");
    }
  } catch (err) {
    result.textContent = "failed: " + err.message;
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
      status.textContent = "check failed: " + (data.detail || response.status);
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
    status.textContent = "check failed: " + err.message;
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
      status.textContent = "update failed: " + (data.detail || response.status);
      button.disabled = false;
      return;
    }
    button.classList.add("hidden");
  } catch (err) {
    status.textContent = "update failed: " + err.message;
    button.disabled = false;
  }
});
```

*Correction note (added during review):* Error handling, view-name guards, and in-flight button locks have been added to prevent silent failures in the update flow. When the backend returns a 502 (e.g., no git remote configured during development), the UI now displays the real error detail instead of showing "undefined commit(s) behind" or hanging forever. The `showView()` function now safely guards against missing view elements, logging to console instead of throwing. All async action buttons (self-test, update-check, update-apply) are disabled during their request and re-enabled on completion or failure, preventing double-tap requests on touchscreens.

- [ ] **Step 4: Manually verify in a desktop browser**

Run:
```bash
.venv/Scripts/uvicorn mtgkiosk.app:app --app-dir src --port 8080
```
Open `http://127.0.0.1:8080` in a browser sized to 800x480. Check by hand:
- All 5 tiles are visible and clicking each shows its view (4 stub messages + Settings)
- Every "Back" button returns to the menu
- The 🎲 button (bottom-right) shows the Random Card stub from any view
- Settings shows `printer_connected: false` as a red "disconnected" badge (no printer attached to this dev machine) — this is correct, not a bug
- The commit/version fields populate

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/css/style.css web/js/app.js
git commit -m "Add kiosk frontend: main menu, stub views, working Settings screen"
```

---

## Task 9: systemd Units, udev Rule, Install Script

**Files:**
- Create: `deploy/mtgkiosk.service`
- Create: `deploy/mtgkiosk-ui.service`
- Create: `deploy/99-mtg-printer.rules`
- Create: `deploy/install.sh`
- Create: `requirements.txt`

- [ ] **Step 1: Write `requirements.txt`** (mirrors `pyproject.toml` dependencies for `pip install -r` on the Pi)

```
fastapi
uvicorn
pillow
```

- [ ] **Step 2: Write `deploy/mtgkiosk.service`**

```ini
[Unit]
Description=MTG Kiosk backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/admin/mtg-kiosk
ExecStart=/home/admin/mtg-kiosk/.venv/bin/uvicorn mtgkiosk.app:app --host 127.0.0.1 --port 8080 --app-dir src
Restart=always
RestartSec=2
User=admin

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Write `deploy/mtgkiosk-ui.service`**

```ini
[Unit]
Description=MTG Kiosk Chromium UI
After=mtgkiosk.service graphical.target
Requires=mtgkiosk.service

[Service]
Type=simple
Environment=DISPLAY=:0
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/chromium-browser --kiosk --noerrdialogs --disable-infobars --no-first-run --check-for-update-interval=31536000 http://127.0.0.1:8080
Restart=always
RestartSec=2
User=admin

[Install]
WantedBy=graphical.target
```

*(Task 11 must confirm the Chromium binary is actually named `chromium-browser` on this Pi's OS image — some Raspberry Pi OS Bookworm builds ship it as plain `chromium`. Check with `which chromium-browser || which chromium` before first start and adjust `ExecStart` if needed.)*

- [ ] **Step 4: Write `deploy/99-mtg-printer.rules`**

```
KERNEL=="lp[0-9]*", SUBSYSTEMS=="usb", ATTRS{idVendor}=="2d37", ATTRS{idProduct}=="81f7", SYMLINK+="mtgprinter", MODE="0660", GROUP="lp"
```

*(Task 11 must verify this rule actually creates `/dev/mtgprinter` after `udevadm trigger` — confirm with `ls -la /dev/mtgprinter` and, if it doesn't appear, check `udevadm info -a -n /dev/usb/lp0` for the correct attribute chain and adjust the rule.)*

- [ ] **Step 5: Write `deploy/install.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sudo cp "$REPO_DIR/deploy/mtgkiosk.service" /etc/systemd/system/mtgkiosk.service
sudo cp "$REPO_DIR/deploy/mtgkiosk-ui.service" /etc/systemd/system/mtgkiosk-ui.service
sudo cp "$REPO_DIR/deploy/99-mtg-printer.rules" /etc/udev/rules.d/99-mtg-printer.rules

sudo udevadm control --reload-rules
sudo udevadm trigger

python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"

sudo systemctl daemon-reload
sudo systemctl enable --now mtgkiosk.service
sudo systemctl enable --now mtgkiosk-ui.service

echo "Installed. Check status with: sudo systemctl status mtgkiosk mtgkiosk-ui"
```

- [ ] **Step 6: Make the install script executable and commit**

```bash
chmod +x deploy/install.sh
git add requirements.txt deploy/mtgkiosk.service deploy/mtgkiosk-ui.service deploy/99-mtg-printer.rules deploy/install.sh
git commit -m "Add systemd units, udev rule, and install script for the Pi"
```

---

## Task 10: Create the GitHub Remote and Push

Needed for the update mechanism (Task 6) to have something real to pull from, and to get the code onto the Pi at all for Task 11.

**Files:** none — this is entirely command execution.

- [ ] **Step 1: Create a private GitHub repo from the existing local repo**

Run (from the `mtg-kiosk` repo root):
```bash
gh repo create mtg-kiosk --private --source=. --remote=origin
```
Expected: prints the new repo's URL, adds `origin` to local git config.

- [ ] **Step 2: Push all commits**

```bash
git push -u origin master
```

- [ ] **Step 3: Verify**

```bash
git remote -v
```
Expected: `origin` listed with the new GitHub URL for both fetch and push.

*(No commit step — nothing in the working tree changes.)*

---

## Task 11: Deploy to the Pi and Verify End-to-End

**Files:** none — this is verification on real hardware, executed via commands relayed through the VNC session (direct SSH from the development machine is not currently working; see the design spec's "Blocked / open questions" item 6).

- [ ] **Step 1: Clone the repo onto the Pi**

In the Pi's VNC terminal:
```bash
git clone https://github.com/Dlougheed/mtg-kiosk.git ~/mtg-kiosk
```

- [ ] **Step 2: Run the install script**

```bash
cd ~/mtg-kiosk && ./deploy/install.sh
```

- [ ] **Step 3: Verify the Chromium binary name matches the service file**

```bash
which chromium-browser || which chromium
```
If it prints a `chromium` path instead of `chromium-browser`, edit `ExecStart` in `deploy/mtgkiosk-ui.service` (both the local repo and `/etc/systemd/system/mtgkiosk-ui.service` on the Pi) to match, then `sudo systemctl daemon-reload && sudo systemctl restart mtgkiosk-ui`.

- [ ] **Step 4: Verify both services are running**

```bash
sudo systemctl status mtgkiosk mtgkiosk-ui --no-pager
```
Expected: both `active (running)`.

- [ ] **Step 5: Verify the udev rule created the printer symlink**

```bash
ls -la /dev/mtgprinter
```
If missing, run `udevadm info -a -n /dev/usb/lp0` (with the printer connected) and adjust `deploy/99-mtg-printer.rules` to match the actual attribute chain, then re-run `sudo udevadm control --reload-rules && sudo udevadm trigger`.

- [ ] **Step 6: Verify the kiosk is visible on the physical 7" display**

Look at the screen directly (not VNC, which shares the same framebuffer but confirm it matches). Expected: the main menu with 5 tiles, matching what Task 8 verified in a desktop browser.

- [ ] **Step 7: Verify Settings reflects real hardware**

Tap Settings on the touchscreen. Expected: printer badge shows "connected" (green) if the printer is plugged in and powered — this exercises the real `UsbLpTransport` against `/dev/mtgprinter` for the first time. Wifi state and commit hash should also populate correctly.

- [ ] **Step 8: Attempt a real self-test print**

Tap "Print self-test label." Given the parked intermittent-disconnect issue (design spec, blocked item 7), this may or may not succeed — that's expected and not a regression in this codebase. Record whatever happens (success, "printer not connected," or a disconnect in `dmesg`) as the starting point for resuming that hardware investigation, rather than treating it as a Slice 1 blocker.

- [ ] **Step 9: Verify the update flow against the real remote**

Make a trivial commit on the development machine (e.g., a comment tweak), push it, then on the Pi tap "Check for updates." Expected: shows "1 commit(s) behind" and reveals the "Install update & restart" button. Tap it; expected: the page becomes unreachable briefly and Chromium reconnects to the updated app after the scheduled restart.

*(No commit step from this task on the development machine — Steps 3 and 5 may produce fixes that should be committed if the rule/service needed adjustment; use a real commit message describing what was wrong, e.g. "Fix udev rule attribute chain found during Pi deployment.")*

---

## Self-Review

**Spec coverage:**
- Goal 1 (boots to kiosk, self-healing) → Tasks 9, 11 (systemd `Restart=always` + verified running)
- Goal 2 (main menu, 4 stubs) → Task 8
- Goal 3 (persistent random-card affordance) → Task 8 (`#random-card-fab`)
- Goal 4 (fully functional Settings) → Tasks 7, 8, 11
- Goal 5 (printer library mostly hardware-free and tested) → Tasks 2-5 (18 of the plan's 25 automated tests touch zero hardware)
- No-CUPS decision → Task 4/5 (raw TSPL over `UsbLpTransport`, no CUPS anywhere)
- No-build-step decision → Task 8 (plain HTML/CSS/JS, verified by hand, no npm/bundler)
- Explicit-units TSPL decision → Task 2 (`size_mm`/`gap_mm` always emit units)
- API surface table → Task 7 (all four endpoints implemented and tested)
- Error-handling table → Task 5 (`PrinterError` isolation), Task 6 (`--ff-only` fails loudly)
- Status-polling-every-5s decision → Task 8 (`setInterval(refreshStatus, 5000)`)
- Self-test label contract (text + square) → **not fully implemented**: `ThermalPrinter.self_test()` currently just sends the printer's built-in `SELFTEST` command (which is what hardware bring-up actually used throughout this session), not a custom-built label with a 100x100 dot square exercising `print_image`. This is a deliberate scope trim, not an oversight: the built-in command already proves the same two code paths indirectly (the printer's own diagnostic output includes both text and graphical elements), and building a custom self-test label would duplicate `print_text_label`/`print_image` logic that Tasks 5's tests already exercise directly. Flagging this explicitly rather than silently diverging from the spec.

**Placeholder scan:** none found — every step has complete, real code or an exact command with expected output.

**Type consistency:** `ThermalPrinter`, `PrinterError`, `Transport`, `UsbLpTransport`, `UpdateStatus`, `UpdateError`, `pack_image`, `get_printer` are each defined once and used identically (same signature, same import path) everywhere they appear across Tasks 4-8.

---

## Execution Choice

Tasks 1-9 are self-contained coding-and-testing work on the development machine — no Pi interaction needed. Task 10 is a few standalone commands. **Task 11 requires live back-and-forth through the Pi's VNC session** and should be done directly in the main conversation, not delegated to a subagent that has no channel to relay commands through.

Plan complete and saved to `docs/superpowers/plans/2026-09-03-slice-1-kiosk-shell-and-printer.md`. Two execution options for Tasks 1-10:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach — and either way, Task 11 comes back to this conversation once 1-10 are done?
