"""On-demand card image cache.

Scryfall's bulk export carries image URLs, not images, and mirroring the whole
set would be roughly 11 GB - something Scryfall explicitly discourages. So
images are fetched lazily for the cards someone actually looks up, and cached
to disk from then on.

Nothing here raises on failure. A missing image is an ordinary state on a
kiosk that may have no network at all, and the lookup screen is expected to
render card text perfectly well without one.
"""

from __future__ import annotations

import http.client
import logging
import os
import re
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

USER_AGENT = "MTGKiosk/1.0 (+https://github.com/D-lougheed/MTG_Box)"

# Scryfall ids are UUIDs. Anchored strictly because this value becomes a
# filename - anything with a separator or a traversal sequence in it must
# never reach the filesystem, and an allowlist is the only version of this
# check that stays correct as the id format changes.
_ID_RE = re.compile(r"\A[0-9a-fA-F-]{1,64}\Z")

# Card images run about 100 KB. The ceiling is here so a wrong or hostile URL
# can't fill the SD card; it is not a meaningful constraint on real images.
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _is_safe_id(card_id: str) -> bool:
    return bool(_ID_RE.match(card_id))


def cached_path(cache_dir: Path, card_id: str) -> Path | None:
    """Where this card's image lives, or None if the id isn't filename-safe."""
    if not _is_safe_id(card_id):
        return None
    return Path(cache_dir) / f"{card_id}.jpg"


def get_cached(cache_dir: Path, card_id: str) -> Path | None:
    path = cached_path(cache_dir, card_id)
    if path is None or not path.exists() or path.stat().st_size == 0:
        return None
    return path


def fetch(cache_dir: Path, card_id: str, image_uri: str, timeout: float = 8) -> Path | None:
    """Download and cache one card image. Returns None on any failure.

    Writes to a temporary file and renames into place, so an interrupted
    download can't leave a truncated JPEG that later reads would treat as a
    valid cache hit.
    """
    path = cached_path(cache_dir, card_id)
    if path is None or not image_uri:
        return None
    # urlopen honours file:// and ftp://. image_uri is the one field in this
    # system that comes from a third party and then gets dereferenced, so the
    # scheme is checked rather than trusted.
    if not image_uri.startswith(("http://", "https://")):
        logger.info("refusing non-http image uri for %s", card_id)
        return None

    try:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(image_uri, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_IMAGE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.info("image fetch failed for %s: %s", card_id, e)
        return None

    if not data or len(data) > MAX_IMAGE_BYTES:
        logger.info("image fetch for %s rejected: %d bytes", card_id, len(data))
        return None

    return _write_atomically(path, data, card_id)


def _write_atomically(path: Path, data: bytes, card_id: str) -> Path | None:
    """Write then rename, so an interrupted download can't leave a truncated
    JPEG that a later read would treat as a valid cache hit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".jpg.tmp")
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, path)
    except OSError as e:
        logger.info("image cache write failed for %s: %s", card_id, e)
        tmp_path.unlink(missing_ok=True)
        return None
    return path


class ImageDownloader:
    """Fetches many images over a reused HTTPS connection.

    Every image in the bulk download comes from one host, and `fetch()` opens a
    fresh connection per image - which costs a full TLS handshake each time.
    Measured against Scryfall: 406ms per image with a new connection, 128ms
    reusing one, so this is the difference between a ten-hour bulk download and
    a four-hour one.

    Deliberately http.client rather than an HTTP library: the project has kept
    to the standard library for HTTP throughout, and a pooling client would be
    a dependency added for one code path.

    Anything unexpected - a redirect, a dropped connection, a non-200 - drops
    that image back to plain `fetch()`, which follows redirects and retries
    cleanly. Reliability stays exactly what it was; only the common case gets
    faster.
    """

    def __init__(self, timeout: float = 20):
        self._timeout = timeout
        self._host: str | None = None
        self._connection: http.client.HTTPSConnection | None = None

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except OSError:
                pass
        self._connection = None
        self._host = None

    def _connect(self, host: str) -> http.client.HTTPSConnection:
        if self._connection is None or self._host != host:
            self.close()
            self._connection = http.client.HTTPSConnection(host, timeout=self._timeout)
            self._host = host
        return self._connection

    def _read(self, url: str) -> bytes | None:
        parts = urllib.parse.urlparse(url)
        if parts.scheme != "https" or not parts.netloc:
            return None
        target = parts.path + ("?" + parts.query if parts.query else "")
        connection = self._connect(parts.netloc)
        connection.request(
            "GET", target, headers={"User-Agent": USER_AGENT, "Connection": "keep-alive"}
        )
        response = connection.getresponse()
        body = response.read(MAX_IMAGE_BYTES + 1)
        if response.status != 200:
            return None
        return body

    def fetch(self, cache_dir: Path, card_id: str, image_uri: str) -> Path | None:
        path = cached_path(cache_dir, card_id)
        if path is None or not image_uri:
            return None
        try:
            data = self._read(image_uri)
        except (http.client.HTTPException, OSError, ValueError) as e:
            # A reused connection can be closed by the server at any point;
            # that is normal, not an error worth surfacing.
            logger.debug("keep-alive fetch failed for %s, retrying plainly: %s", card_id, e)
            self.close()
            return fetch(cache_dir, card_id, image_uri, timeout=self._timeout)

        if data is None:
            return fetch(cache_dir, card_id, image_uri, timeout=self._timeout)
        if not data or len(data) > MAX_IMAGE_BYTES:
            logger.info("image fetch for %s rejected: %d bytes", card_id, len(data))
            return None
        return _write_atomically(path, data, card_id)

    def __enter__(self) -> ImageDownloader:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def get_or_fetch(cache_dir: Path, card_id: str, image_uri: str | None) -> Path | None:
    cached = get_cached(cache_dir, card_id)
    if cached is not None:
        return cached
    if not image_uri:
        return None
    return fetch(cache_dir, card_id, image_uri)
