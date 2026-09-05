import urllib.error
from unittest.mock import MagicMock, patch

from mtgkiosk import images

CARD_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _fake_response(data: bytes):
    response = MagicMock()
    response.read.return_value = data
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *a: False
    return response


def test_cached_path_rejects_ids_that_are_not_filename_safe():
    assert images.cached_path("/tmp", "../../etc/passwd") is None
    assert images.cached_path("/tmp", "a/b") is None
    assert images.cached_path("/tmp", "") is None
    assert images.cached_path("/tmp", CARD_ID) is not None


def test_get_cached_returns_none_when_missing(tmp_path):
    assert images.get_cached(tmp_path, CARD_ID) is None


def test_get_cached_ignores_zero_byte_file(tmp_path):
    (tmp_path / f"{CARD_ID}.jpg").write_bytes(b"")
    assert images.get_cached(tmp_path, CARD_ID) is None


def test_fetch_writes_and_returns_path(tmp_path):
    with patch("mtgkiosk.images.urllib.request.urlopen", return_value=_fake_response(b"jpegbytes")):
        path = images.fetch(tmp_path, CARD_ID, "https://example.test/card.jpg")
    assert path is not None
    assert path.read_bytes() == b"jpegbytes"


def test_fetch_returns_none_on_network_error(tmp_path):
    with patch("mtgkiosk.images.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
        assert images.fetch(tmp_path, CARD_ID, "https://example.test/card.jpg") is None


def test_fetch_returns_none_on_timeout(tmp_path):
    with patch("mtgkiosk.images.urllib.request.urlopen", side_effect=TimeoutError("slow")):
        assert images.fetch(tmp_path, CARD_ID, "https://example.test/card.jpg") is None


def test_fetch_rejects_oversized_response(tmp_path):
    oversized = b"x" * (images.MAX_IMAGE_BYTES + 1)
    with patch("mtgkiosk.images.urllib.request.urlopen", return_value=_fake_response(oversized)):
        assert images.fetch(tmp_path, CARD_ID, "https://example.test/card.jpg") is None
    assert list(tmp_path.iterdir()) == []


def test_fetch_rejects_empty_response(tmp_path):
    with patch("mtgkiosk.images.urllib.request.urlopen", return_value=_fake_response(b"")):
        assert images.fetch(tmp_path, CARD_ID, "https://example.test/card.jpg") is None


def test_fetch_leaves_no_temp_file_behind(tmp_path):
    with patch("mtgkiosk.images.urllib.request.urlopen", return_value=_fake_response(b"jpegbytes")):
        images.fetch(tmp_path, CARD_ID, "https://example.test/card.jpg")
    assert [p.name for p in tmp_path.iterdir()] == [f"{CARD_ID}.jpg"]


def test_get_or_fetch_prefers_cache_and_does_not_hit_network(tmp_path):
    (tmp_path / f"{CARD_ID}.jpg").write_bytes(b"cached")
    with patch("mtgkiosk.images.urllib.request.urlopen") as mock_urlopen:
        path = images.get_or_fetch(tmp_path, CARD_ID, "https://example.test/card.jpg")
    assert path.read_bytes() == b"cached"
    mock_urlopen.assert_not_called()


def test_get_or_fetch_returns_none_without_an_image_uri(tmp_path):
    assert images.get_or_fetch(tmp_path, CARD_ID, None) is None
