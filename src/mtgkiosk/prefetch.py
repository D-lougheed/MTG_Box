"""Bulk pre-download of card images, so the kiosk works with no network at all.

Two caches, both keyed by card id: the full card image the lookup screen
displays, and the art crop the printer puts on a label. Together they are about
6.2 GB across ~34.6k cards.

Three properties matter more than speed here, because this is a multi-hour job
on an appliance that can be switched off at any moment:

- **Resumable.** Anything already cached is skipped without a request, so a
  re-run after a reboot costs a directory scan rather than another 3.5 hours.
- **Cancellable.** `should_stop` is checked every card, so stopping is quick
  rather than waiting out the remaining thousands.
- **Paced.** Scryfall asks for 50-100ms between requests and this makes ~69k of
  them against a free service. The delay applies only to real downloads - a
  resume skims cached entries at full speed.

Measured end to end at 5.5 images/sec, about 3.5 hours for a full run: 100ms of
that per image is the deliberate pacing, ~80ms the actual transfer.

A card that fails is counted and stepped over. Losing hours of progress because
one image 404s would be absurd.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path

from . import images

logger = logging.getLogger(__name__)

REQUEST_DELAY = 0.1

# How often progress reaches the UI. Frequent enough that the count visibly
# moves, which is the only signal a multi-hour job is alive.
PROGRESS_INTERVAL = 0.5

# Measured over a random sample of the real set: ~97 KB per card image and
# ~78 KB per art crop. Used only to refuse a run that clearly cannot fit, so a
# rough figure with headroom beats a precise one.
ESTIMATED_BYTES_PER_CARD = {"normal": 100_000, "art_crop": 80_000}
FREE_SPACE_MARGIN = 500 * 1024 * 1024


class PrefetchError(Exception):
    pass


@dataclass(frozen=True)
class PrefetchProgress:
    total: int = 0
    done: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "done": self.done,
            "downloaded": self.downloaded,
            "skipped": self.skipped,
            "failed": self.failed,
        }


ProgressCallback = Callable[[PrefetchProgress], None]
StopCheck = Callable[[], bool]


def _targets(db_path: Path, kinds: tuple[str, ...]) -> Iterator[tuple[str, str, str]]:
    """(card_id, kind, url) for every image worth fetching, streamed.

    Streamed rather than listed because holding ~69k rows for a job that runs
    for hours is needless, and the cursor keeps the read short-lived.
    """
    columns = {"normal": "image_uri", "art_crop": "art_crop_uri"}
    selected = [columns[kind] for kind in kinds]
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(f"SELECT id, {', '.join(selected)} FROM cards ORDER BY id"):
            for kind in kinds:
                url = row[columns[kind]]
                if url:
                    yield row["id"], kind, url


def count_targets(db_path: Path, kinds: tuple[str, ...] = ("normal", "art_crop")) -> int:
    return sum(1 for _ in _targets(db_path, kinds))


def estimate_bytes(db_path: Path, kinds: tuple[str, ...] = ("normal", "art_crop")) -> int:
    with closing(sqlite3.connect(str(db_path))) as conn:
        total = 0
        for kind in kinds:
            column = {"normal": "image_uri", "art_crop": "art_crop_uri"}[kind]
            n = conn.execute(f"SELECT COUNT(*) FROM cards WHERE {column} IS NOT NULL").fetchone()[0]
            total += n * ESTIMATED_BYTES_PER_CARD[kind]
    return total


def check_free_space(target_dir: Path, needed: int) -> None:
    """Refuse a run that cannot finish, rather than filling the card and failing late.

    A kiosk that fills its own storage stops being a kiosk: SQLite writes fail,
    the browser profile fails, and none of it says why.
    """
    probe = Path(target_dir)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(str(probe)).free
    if free < needed + FREE_SPACE_MARGIN:
        raise PrefetchError(
            f"not enough space: needs about {needed / 1e9:.1f} GB plus headroom, "
            f"{free / 1e9:.1f} GB free"
        )


def prefetch(
    db_path: Path,
    caches: dict[str, Path],
    kinds: tuple[str, ...] = ("normal", "art_crop"),
    progress: ProgressCallback | None = None,
    should_stop: StopCheck | None = None,
    delay: float = REQUEST_DELAY,
) -> PrefetchProgress:
    """Download every missing image. Returns the final progress."""
    stop = should_stop or (lambda: False)
    state = PrefetchProgress(total=count_targets(db_path, kinds))
    if progress:
        progress(state)
    last_report = time.monotonic()

    # One reused connection for the whole run. Every image comes from the same
    # host, and a fresh TLS handshake per image measured 406ms against 128ms
    # reusing one - the difference between a ten-hour download and a four-hour
    # one.
    with images.ImageDownloader() as downloader:
        for card_id, kind, url in _targets(db_path, kinds):
            if stop():
                logger.info("image prefetch stopped after %d of %d", state.done, state.total)
                break

            cache_dir = caches[kind]
            if images.get_cached(cache_dir, card_id) is not None:
                state = replace(state, done=state.done + 1, skipped=state.skipped + 1)
            elif downloader.fetch(cache_dir, card_id, url) is not None:
                state = replace(state, done=state.done + 1, downloaded=state.downloaded + 1)
                # Only after a real request: a resume must not crawl through
                # thousands of already-cached entries at 100ms each.
                time.sleep(delay)
            else:
                state = replace(state, done=state.done + 1, failed=state.failed + 1)
                time.sleep(delay)

            # Reported on a clock rather than every Nth card. Counting made the
            # number sit still for ~17s at real download rates, which on a
            # kiosk is indistinguishable from a hang.
            now = time.monotonic()
            if progress and now - last_report >= PROGRESS_INTERVAL:
                progress(state)
                last_report = now

    if progress:
        progress(state)
    return state
