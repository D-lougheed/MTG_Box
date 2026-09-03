import logging
import threading
import time

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


class RaisingIsPresentTransport:
    def is_present(self) -> bool:
        raise PermissionError("simulated stat failure")

    def write(self, data: bytes) -> None:
        raise AssertionError("write should never be reached")


def test_is_connected_returns_false_when_is_present_raises():
    printer = ThermalPrinter(transport=RaisingIsPresentTransport())
    assert printer.is_connected() is False


def test_self_test_raises_printer_error_when_is_present_raises():
    printer = ThermalPrinter(transport=RaisingIsPresentTransport())
    with pytest.raises(PrinterError):
        printer.self_test()


class NonOSErrorWriteTransport:
    def is_present(self) -> bool:
        return True

    def write(self, data: bytes) -> None:
        raise RuntimeError("simulated non-OSError failure")


def test_self_test_raises_printer_error_on_non_os_error_write_failure():
    printer = ThermalPrinter(transport=NonOSErrorWriteTransport())
    with pytest.raises(PrinterError):
        printer.self_test()


def test_print_text_label_raises_printer_error_when_is_present_raises():
    printer = ThermalPrinter(transport=RaisingIsPresentTransport())
    with pytest.raises(PrinterError):
        printer.print_text_label(["hi"])


class SlowTransport:
    def __init__(self):
        self.present = True
        self.events = []
        self._events_lock = threading.Lock()

    def is_present(self):
        return self.present

    def write(self, data):
        thread_name = threading.current_thread().name
        with self._events_lock:
            self.events.append((thread_name, "start"))
        time.sleep(0.05)
        with self._events_lock:
            self.events.append((thread_name, "end"))


def test_send_is_serialized_across_threads():
    transport = SlowTransport()
    printer = ThermalPrinter(transport=transport)

    t1 = threading.Thread(target=printer.self_test, name="t1")
    t2 = threading.Thread(target=printer.self_test, name="t2")
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert transport.events[0][1] == "start"
    assert transport.events[1] == (transport.events[0][0], "end")
    assert transport.events[2][1] == "start"
    assert transport.events[3] == (transport.events[2][0], "end")


def test_send_logs_warning_on_write_failure(caplog):
    printer = ThermalPrinter(transport=FakeTransport(fail=True))
    with caplog.at_level(logging.WARNING, logger="mtgkiosk.printer.device"):
        with pytest.raises(PrinterError):
            printer.self_test()
    assert any("printer write failed" in r.message for r in caplog.records)


def test_send_logs_warning_when_disconnected(caplog):
    printer = ThermalPrinter(transport=FakeTransport(present=False))
    with caplog.at_level(logging.WARNING, logger="mtgkiosk.printer.device"):
        with pytest.raises(PrinterError):
            printer.self_test()
    assert any("printer write failed" in r.message for r in caplog.records)
