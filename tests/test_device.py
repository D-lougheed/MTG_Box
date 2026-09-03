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
