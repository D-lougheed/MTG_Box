import subprocess
import traceback
from unittest.mock import MagicMock, patch

import pytest

from mtgkiosk.wifi import WifiError, WifiNetwork, connect, scan


def _fake_result(stdout="", stderr="", returncode=0):
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


def test_scan_parses_networks():
    fake_output = "MyNetwork:80:WPA2\nOpenNet:60:\n"
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stdout=fake_output)) as mock_run:
        networks = scan()
    assert networks == [
        WifiNetwork(ssid="MyNetwork", signal=80, secured=True),
        WifiNetwork(ssid="OpenNet", signal=60, secured=False),
    ]
    assert mock_run.call_args.args[0] == ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"]


def test_scan_deduplicates_by_ssid_keeping_strongest_signal():
    fake_output = "TheGuild:40:WPA2\nTheGuild:75:WPA2\nTheGuild:60:WPA2\n"
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stdout=fake_output)):
        networks = scan()
    assert networks == [WifiNetwork(ssid="TheGuild", signal=75, secured=True)]


def test_scan_sorts_by_signal_descending():
    fake_output = "Weak:20:\nStrong:90:\nMedium:50:\n"
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stdout=fake_output)):
        networks = scan()
    assert [n.ssid for n in networks] == ["Strong", "Medium", "Weak"]


def test_scan_drops_hidden_networks_with_empty_ssid():
    fake_output = ":45:WPA2\nRealNetwork:70:\n"
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stdout=fake_output)):
        networks = scan()
    assert [n.ssid for n in networks] == ["RealNetwork"]


def test_scan_unescapes_colons_in_ssid():
    fake_output = "Office\\:Wifi:65:WPA2\n"
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stdout=fake_output)):
        networks = scan()
    assert networks == [WifiNetwork(ssid="Office:Wifi", signal=65, secured=True)]


def test_scan_raises_wifi_error_on_nonzero_exit():
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stderr="nmcli error", returncode=1)):
        with pytest.raises(WifiError):
            scan()


def test_scan_raises_wifi_error_on_timeout():
    with patch("mtgkiosk.wifi.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="nmcli", timeout=10)):
        with pytest.raises(WifiError):
            scan()


def test_connect_includes_password_when_given():
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result()) as mock_run:
        connect("MyNetwork", "hunter2")
    assert mock_run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "MyNetwork", "password", "hunter2"]


def test_connect_omits_password_for_open_network():
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result()) as mock_run:
        connect("OpenNet", None)
    assert mock_run.call_args.args[0] == ["nmcli", "device", "wifi", "connect", "OpenNet"]


def test_connect_raises_wifi_error_on_failure():
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(returncode=1)):
        with pytest.raises(WifiError):
            connect("MyNetwork", "wrongpassword")


def test_connect_error_message_never_contains_the_password():
    with patch("mtgkiosk.wifi.subprocess.run", return_value=_fake_result(stderr="Error: hunter2 rejected", returncode=1)):
        try:
            connect("MyNetwork", "hunter2")
            assert False, "expected WifiError"
        except WifiError as e:
            assert "hunter2" not in str(e)


def test_connect_raises_wifi_error_on_timeout():
    with patch("mtgkiosk.wifi.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="nmcli", timeout=30)):
        with pytest.raises(WifiError):
            connect("MyNetwork", "hunter2")


def test_connect_timeout_does_not_leak_password_via_exception_chain():
    with patch(
        "mtgkiosk.wifi.subprocess.run",
        side_effect=subprocess.TimeoutExpired(
            cmd=["nmcli", "device", "wifi", "connect", "MyNetwork", "password", "hunter2"], timeout=30
        ),
    ):
        try:
            connect("MyNetwork", "hunter2")
            assert False, "expected WifiError"
        except WifiError as e:
            full_traceback = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            # The exception chain should be severed so TimeoutExpired isn't printed
            assert "TimeoutExpired" not in full_traceback
            assert e.__cause__ is None


def test_scan_timeout_does_not_chain_original_exception():
    with patch("mtgkiosk.wifi.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="nmcli", timeout=10)):
        try:
            scan()
            assert False, "expected WifiError"
        except WifiError as e:
            assert e.__cause__ is None
