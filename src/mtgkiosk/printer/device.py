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
        return self._transport.is_present()

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
        if not self._transport.is_present():
            raise PrinterError("printer not connected")
        try:
            self._transport.write(data)
        except OSError as e:
            raise PrinterError(f"write failed: {e}") from e
