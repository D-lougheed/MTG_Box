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
