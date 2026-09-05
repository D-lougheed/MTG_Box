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


# --- keep-alive downloader --------------------------------------------------


class _FakeResponse:
    def __init__(self, status=200, body=b"jpegbytes"):
        self.status = status
        self._body = body

    def read(self, _limit=None):
        return self._body


class _FakeConnection:
    """Records requests so connection reuse can be asserted, not assumed."""

    instances = []

    def __init__(self, host, timeout=None):
        self.host = host
        self.requests = []
        self.closed = False
        self.response = _FakeResponse()
        self.raise_on_request = None
        _FakeConnection.instances.append(self)

    def request(self, method, target, headers=None):
        if self.raise_on_request:
            raise self.raise_on_request
        self.requests.append(target)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def _patch_connection(monkeypatch):
    _FakeConnection.instances = []
    monkeypatch.setattr(images.http.client, "HTTPSConnection", _FakeConnection)
    return _FakeConnection


def test_downloader_writes_the_image(tmp_path, monkeypatch):
    _patch_connection(monkeypatch)
    with images.ImageDownloader() as downloader:
        path = downloader.fetch(tmp_path, CARD_ID, "https://cards.test/a.jpg")
    assert path.read_bytes() == b"jpegbytes"


def test_downloader_reuses_one_connection_across_images(tmp_path, monkeypatch):
    """The whole point: a TLS handshake per image is 406ms against 128ms."""
    fake = _patch_connection(monkeypatch)
    ids = ["aaaaaaaa", "bbbbbbbb", "cccccccc"]
    with images.ImageDownloader() as downloader:
        for card_id in ids:
            downloader.fetch(tmp_path, card_id, f"https://cards.test/{card_id}.jpg")

    assert len(fake.instances) == 1
    assert len(fake.instances[0].requests) == 3


def test_downloader_opens_a_new_connection_for_a_different_host(tmp_path, monkeypatch):
    fake = _patch_connection(monkeypatch)
    with images.ImageDownloader() as downloader:
        downloader.fetch(tmp_path, "aaaaaaaa", "https://one.test/a.jpg")
        downloader.fetch(tmp_path, "bbbbbbbb", "https://two.test/b.jpg")
    assert [c.host for c in fake.instances] == ["one.test", "two.test"]


def test_downloader_falls_back_to_a_plain_fetch_on_a_dropped_connection(tmp_path, monkeypatch):
    fake = _patch_connection(monkeypatch)
    downloader = images.ImageDownloader()
    downloader.fetch(tmp_path, "aaaaaaaa", "https://cards.test/a.jpg")
    fake.instances[0].raise_on_request = ConnectionResetError("server hung up")

    with patch("mtgkiosk.images.urllib.request.urlopen", return_value=_fake_response(b"viaplain")):
        path = downloader.fetch(tmp_path, "bbbbbbbb", "https://cards.test/b.jpg")

    assert path.read_bytes() == b"viaplain"
    assert fake.instances[0].closed


def test_downloader_falls_back_on_a_non_200(tmp_path, monkeypatch):
    # Covers redirects too: http.client doesn't follow them, urlopen does.
    fake = _patch_connection(monkeypatch)
    downloader = images.ImageDownloader()
    downloader.fetch(tmp_path, "aaaaaaaa", "https://cards.test/a.jpg")
    fake.instances[0].response = _FakeResponse(status=302, body=b"")

    with patch("mtgkiosk.images.urllib.request.urlopen", return_value=_fake_response(b"redirected")):
        path = downloader.fetch(tmp_path, "bbbbbbbb", "https://cards.test/b.jpg")
    assert path.read_bytes() == b"redirected"


def test_downloader_rejects_an_oversized_response(tmp_path, monkeypatch):
    fake = _patch_connection(monkeypatch)
    downloader = images.ImageDownloader()
    downloader.fetch(tmp_path, "aaaaaaaa", "https://cards.test/a.jpg")
    fake.instances[0].response = _FakeResponse(body=b"x" * (images.MAX_IMAGE_BYTES + 1))
    assert downloader.fetch(tmp_path, "bbbbbbbb", "https://cards.test/b.jpg") is None


def test_downloader_refuses_a_non_https_url(tmp_path, monkeypatch):
    _patch_connection(monkeypatch)
    downloader = images.ImageDownloader()
    with patch("mtgkiosk.images.urllib.request.urlopen") as urlopen:
        assert downloader.fetch(tmp_path, CARD_ID, "file:///etc/passwd") is None
    urlopen.assert_not_called()


def test_downloader_close_is_safe_to_call_twice(monkeypatch):
    _patch_connection(monkeypatch)
    downloader = images.ImageDownloader()
    downloader.close()
    downloader.close()
