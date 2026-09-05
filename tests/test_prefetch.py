import sqlite3
from unittest.mock import patch

import pytest

from mtgkiosk import cards, prefetch


def _db(tmp_path, rows):
    db_path = tmp_path / "cards.sqlite"
    conn = sqlite3.connect(str(db_path))
    cards.create_schema(conn)
    conn.executemany(
        "INSERT INTO cards (id, name, image_uri, art_crop_uri) VALUES (?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()
    return db_path


ROWS = [
    ("aaaaaaaa", "One", "https://img.test/1.jpg", "https://img.test/1-art.jpg"),
    ("bbbbbbbb", "Two", "https://img.test/2.jpg", "https://img.test/2-art.jpg"),
    ("cccccccc", "Three", "https://img.test/3.jpg", None),
]


def _caches(tmp_path):
    return {"normal": tmp_path / "images", "art_crop": tmp_path / "art"}


def test_counts_every_available_image_across_both_kinds(tmp_path):
    # Three cards, but one has no art crop: five targets, not six.
    assert prefetch.count_targets(_db(tmp_path, ROWS)) == 5


def test_downloads_each_missing_image_once(tmp_path):
    db_path = _db(tmp_path, ROWS)
    fetched = []

    def fake_fetch(cache_dir, card_id, url, timeout=8):
        fetched.append((cache_dir.name, card_id))
        path = prefetch.images.cached_path(cache_dir, card_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")
        return path

    with patch.object(prefetch.images, "fetch", fake_fetch):
        result = prefetch.prefetch(db_path, _caches(tmp_path), delay=0)

    assert result.downloaded == 5
    assert result.failed == 0
    assert result.done == result.total == 5
    assert sorted(fetched) == sorted(
        [("art", "aaaaaaaa"), ("art", "bbbbbbbb"),
         ("images", "aaaaaaaa"), ("images", "bbbbbbbb"), ("images", "cccccccc")]
    )


def test_resume_skips_cached_images_without_requesting_them(tmp_path):
    """A re-run after a reboot must cost a directory scan, not another 2.5 hours."""
    db_path = _db(tmp_path, ROWS)
    caches = _caches(tmp_path)
    caches["normal"].mkdir(parents=True)
    (caches["normal"] / "aaaaaaaa.jpg").write_bytes(b"already here")

    requested = []

    def fake_fetch(cache_dir, card_id, url, timeout=8):
        requested.append((cache_dir.name, card_id))
        path = prefetch.images.cached_path(cache_dir, card_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")
        return path

    with patch.object(prefetch.images, "fetch", fake_fetch):
        result = prefetch.prefetch(db_path, caches, delay=0)

    assert result.skipped == 1
    assert result.downloaded == 4
    assert ("images", "aaaaaaaa") not in requested


def test_a_failed_image_is_counted_and_stepped_over(tmp_path):
    # Losing hours of progress because one image 404s would be absurd.
    db_path = _db(tmp_path, ROWS)

    def flaky_fetch(cache_dir, card_id, url, timeout=8):
        if card_id == "bbbbbbbb":
            return None
        path = prefetch.images.cached_path(cache_dir, card_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")
        return path

    with patch.object(prefetch.images, "fetch", flaky_fetch):
        result = prefetch.prefetch(db_path, _caches(tmp_path), delay=0)

    assert result.failed == 2
    assert result.downloaded == 3
    assert result.done == 5


def test_stopping_halts_promptly_rather_than_running_to_completion(tmp_path):
    db_path = _db(tmp_path, ROWS)
    seen = []

    def fake_fetch(cache_dir, card_id, url, timeout=8):
        seen.append(card_id)
        path = prefetch.images.cached_path(cache_dir, card_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"jpeg")
        return path

    with patch.object(prefetch.images, "fetch", fake_fetch):
        result = prefetch.prefetch(
            db_path, _caches(tmp_path), should_stop=lambda: len(seen) >= 2, delay=0
        )

    assert result.done < result.total
    assert len(seen) == 2


def test_progress_reports_the_total_before_any_work(tmp_path):
    """The UI shows a denominator immediately, not after the first 25 cards."""
    db_path = _db(tmp_path, ROWS)
    reports = []
    with patch.object(prefetch.images, "fetch", lambda *a, **kw: None):
        prefetch.prefetch(db_path, _caches(tmp_path), progress=reports.append, delay=0)

    assert reports[0].total == 5
    assert reports[0].done == 0
    assert reports[-1].done == 5


def test_delay_is_not_paid_for_cached_entries(tmp_path):
    db_path = _db(tmp_path, ROWS)
    caches = _caches(tmp_path)
    for kind, directory in caches.items():
        directory.mkdir(parents=True)
    for card_id, _, image, art in ROWS:
        if image:
            (caches["normal"] / f"{card_id}.jpg").write_bytes(b"x")
        if art:
            (caches["art_crop"] / f"{card_id}.jpg").write_bytes(b"x")

    slept = []
    with patch.object(prefetch.time, "sleep", slept.append):
        result = prefetch.prefetch(db_path, caches, delay=0.1)

    assert result.skipped == 5
    assert slept == []


def test_check_free_space_raises_when_the_disk_is_too_small(tmp_path):
    with patch.object(prefetch.shutil, "disk_usage") as usage:
        usage.return_value = type("U", (), {"free": 1_000_000})()
        with pytest.raises(prefetch.PrefetchError):
            prefetch.check_free_space(tmp_path, 6_000_000_000)


def test_check_free_space_allows_a_run_that_fits(tmp_path):
    with patch.object(prefetch.shutil, "disk_usage") as usage:
        usage.return_value = type("U", (), {"free": 20_000_000_000})()
        prefetch.check_free_space(tmp_path, 6_000_000_000)


def test_check_free_space_walks_up_to_an_existing_directory(tmp_path):
    # data/ may not exist yet on a fresh install; disk_usage would raise on it.
    prefetch.check_free_space(tmp_path / "nope" / "deeper", 1)


def test_estimate_counts_both_kinds_and_skips_cards_with_no_image(tmp_path):
    per_card = prefetch.ESTIMATED_BYTES_PER_CARD
    # Two cards have both kinds, the third only a full image.
    expected = 3 * per_card["normal"] + 2 * per_card["art_crop"]
    assert prefetch.estimate_bytes(_db(tmp_path, ROWS)) == expected


def test_estimate_is_zero_for_a_database_with_no_images(tmp_path):
    db_path = _db(tmp_path, [("dddddddd", "Artless", None, None)])
    assert prefetch.estimate_bytes(db_path) == 0
