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

import logging
import os
import re
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

    tmp_path = path.with_suffix(".jpg.tmp")
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, path)
    except OSError as e:
        logger.info("image cache write failed for %s: %s", card_id, e)
        tmp_path.unlink(missing_ok=True)
        return None
    return path


def get_or_fetch(cache_dir: Path, card_id: str, image_uri: str | None) -> Path | None:
    cached = get_cached(cache_dir, card_id)
    if cached is not None:
        return cached
    if not image_uri:
        return None
    return fetch(cache_dir, card_id, image_uri)
