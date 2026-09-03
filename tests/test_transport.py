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
