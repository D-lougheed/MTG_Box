"""Build data/cards.sqlite from Scryfall's Oracle Cards bulk export.

Driven by scripts/ingest_cards.py for a manual rebuild, and imported directly by
POST /api/cards/update, which runs ingest() on a background thread - the
kiosk has no terminal, so a database refresh has to be reachable from the
touchscreen.

Scryfall serves the export as gzipped JSONL - one card object per line - so
it is inflated and parsed a line at a time. Peak memory is one card rather
than the ~140 MB export, which matters on a 4 GB Pi that is also running a
browser.

Nothing touches data/cards.sqlite until the entire export has parsed and
committed cleanly - the build happens in data/cards.sqlite.tmp and is renamed
over the real path at the end, so an interrupted ingest leaves whatever
database was already there working rather than a half-populated one.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from contextlib import closing
from dataclasses import fields
from pathlib import Path
from typing import BinaryIO, Callable


from . import cards

logger = logging.getLogger(__name__)

BULK_DATA_URL = "https://api.scryfall.com/bulk-data"
BULK_TYPE = "oracle_cards"

# Scryfall's API docs require clients to identify themselves; anonymous
# traffic gets rate-limited and eventually blocked.
USER_AGENT = "mtg-kiosk/0.1 (+https://github.com/D-lougheed/MTG_Box)"

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "cards.sqlite"

FACE_SEPARATOR = "\n//\n"
BATCH_SIZE = 1000
PROGRESS_INTERVAL = 1000

# Known limitation: urlopen's timeout bounds each individual socket operation,
# not the transfer as a whole. A server that trickles bytes forever keeps the
# ingest alive indefinitely. Bounding total wall time needs a watchdog thread
# cancelling the read from outside, which is more machinery than a manually
# triggered, user-visible refresh warrants - the user can see it is stuck and
# restart the service. Deliberately deferred.
BULK_DATA_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 60

# progress(stage, done, total). `total` is None throughout the download:
# Scryfall's bulk-data index reports the export's size in bytes while the
# parse counts cards, so there is no honest denominator to report. The UI
# shows a running count instead of a percentage; hardcoding an expected card
# count would only rot as Scryfall grows.
ProgressCallback = Callable[[str, int, int | None], None]

# Column order comes from the Card dataclass rather than a second hand-written
# list, so this file cannot drift out of step with cards.SCHEMA.
_FIELDS = tuple(field.name for field in fields(cards.Card))
# OR REPLACE because Oracle Cards is one entry per oracle_id and a collision
# should be impossible - but if Scryfall ever ships one, last-one-wins beats
# aborting the transaction and throwing away a multi-minute download.
_INSERT_SQL = (
    f"INSERT OR REPLACE INTO cards ({', '.join(_FIELDS)}) "
    f"VALUES ({', '.join(['?'] * len(_FIELDS))})"
)

_COLOR_ORDER = "WUBRG"

# Oracle Cards is one entry per oracle id, but "card" there is broader than
# "card you can draw and cast". Art series and front cards carry no rules text
# at all and share their names with the real card, so a lookup for "Delver of
# Secrets" returns three rows of which one is the card. Tokens, emblems,
# schemes, planes and vanguards are supplementary pieces belonging to formats
# this appliance doesn't serve.
#
# Together these are about 10% of the export, so leaving them in would mean a
# random roll landing on a textless art card roughly one time in sixteen.
EXCLUDED_LAYOUTS = frozenset(
    {
        "art_series",
        "front_card",
        "token",
        "double_faced_token",
        "emblem",
        "vanguard",
        "scheme",
        "planar",
    }
)

# A crashed run can leave cards.sqlite.tmp plus SQLite's own sidecars behind.
# Opening on top of a stale hot journal makes SQLite try to roll the old file
# back; deleting the whole set is simpler than reasoning about which
# combinations are recoverable, and none of it is data anyone wants.
_TEMP_SUFFIXES = ("", "-journal", "-wal", "-shm")


class IngestError(Exception):
    pass


def _ignore_progress(stage: str, done: int, total: int | None) -> None:
    pass


def _open_url(url: str, timeout: float):
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise IngestError(f"{url} returned HTTP {e.code} {e.reason}") from e
    except OSError as e:
        # URLError subclasses OSError, as do socket timeouts and DNS failures,
        # so this one clause covers every way the request fails to connect.
        raise IngestError(f"couldn't reach {url}: {e}") from e


def bulk_download_uri(timeout: float = BULK_DATA_TIMEOUT) -> str:
    """The current download URI for the Oracle Cards export.

    Discovered at runtime because Scryfall rotates these URIs daily. A
    hardcoded one is guaranteed to break, and would break as a 404 weeks
    after anyone last touched this file.
    """
    with _open_url(BULK_DATA_URL, timeout) as response:
        try:
            payload = json.load(response)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise IngestError(f"{BULK_DATA_URL} returned malformed JSON") from e
    entries = payload.get("data") if isinstance(payload, dict) else None
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("type") == BULK_TYPE:
            # Scryfall serves gzipped JSONL and advertises it as
            # jsonl_download_uri. `download_uri` is checked as a fallback
            # because it is what the index used to expose, for a single
            # pretty-printed JSON array; if it ever comes back, its bytes are
            # still newline-free per record and would fail loudly at parse
            # rather than silently importing nothing.
            uri = entry.get("jsonl_download_uri") or entry.get("download_uri")
            if uri:
                return str(uri)
            break
    raise IngestError(f"no usable {BULK_TYPE!r} entry in the Scryfall bulk-data index")


def _faces(card: dict) -> list[dict]:
    faces = card.get("card_faces")
    return [face for face in faces if isinstance(face, dict)] if isinstance(faces, list) else []


def _face_value(card: dict, faces: list[dict], key: str) -> str | None:
    """A top-level field, or each face's copy of it joined by FACE_SEPARATOR.

    Keyed off the *absence* of a top-level value rather than a list of
    multi-face layout names, so a layout Scryfall invents later still
    flattens correctly without this file learning its name.

    Empty strings count as absent: transform cards carry `"mana_cost": ""` at
    top level while the real costs sit on the faces, and treating that as a
    present value would silently blank every transform card's cost.

    Faces missing the field are skipped rather than contributing an empty
    segment, so an Equipment // Creature card reports the creature face's
    power as "13" rather than "\\n//\\n13".
    """
    value = card.get(key)
    if value not in (None, ""):
        return str(value)
    parts = [str(face[key]) for face in faces if face.get(key) not in (None, "")]
    return FACE_SEPARATOR.join(parts) or None


def _color_list(card: dict, faces: list[dict], key: str) -> str:
    """Scryfall's colour array, comma-joined: ["W", "U"] -> "W,U".

    Transform layouts carry `colors` per face rather than at top level.
    Colours are a set, not prose, so the faces are unioned into one list in
    WUBRG order instead of being joined with FACE_SEPARATOR like the text
    fields - a card that is blue on both faces is blue, not "U\\n//\\nU".

    A colourless card stores "" rather than NULL, which keeps "colourless"
    distinguishable from a field we failed to read.
    """
    values = card.get(key)
    if not isinstance(values, list):
        merged = [colour for face in faces for colour in face.get(key) or []]
        # str.find rather than str.index so an unexpected letter sorts first
        # instead of raising and killing the whole ingest.
        values = sorted(dict.fromkeys(merged), key=_COLOR_ORDER.find)
    return ",".join(str(colour) for colour in values)


def _image_uri(card: dict, faces: list[dict]) -> str | None:
    """The normal-size JPEG URL, falling back to face 0 on a double-faced card.

    A card with no image anywhere stores NULL rather than failing the ingest:
    the lookup UI already treats a missing image as normal, and losing a
    multi-minute download over one artless card would be absurd.
    """
    for source in (card, *faces[:1]):
        uris = source.get("image_uris")
        if isinstance(uris, dict) and uris.get("normal"):
            return str(uris["normal"])
    return None


def _card_id(card: dict, faces: list[dict]) -> str | None:
    """Scryfall's oracle_id - the identity that is stable across printings.

    `reversible_card` layouts omit oracle_id at top level and put one on each
    face, so face 0's is used there. The printing-specific `id` is a last
    resort; an entry with neither is skipped rather than stored under a
    made-up key that /api/cards/{id} could never resolve.
    """
    for source in (card, *faces):
        oracle_id = source.get("oracle_id")
        if oracle_id:
            return str(oracle_id)
    card_id = card.get("id")
    return str(card_id) if card_id else None


def _cmc(card: dict) -> float | None:
    """Converted mana cost as a float.

    Coerced rather than passed through: Scryfall reports whole costs as ints
    and half-costs (Unstable's) as floats, and the column is REAL.
    """
    try:
        return float(card["cmc"])
    except (KeyError, TypeError, ValueError):
        return None


def card_row(card: dict) -> tuple | None:
    """One Scryfall bulk entry flattened to a cards-table row.

    Returns None for an entry with no usable id or name, which the caller
    skips: one malformed record must not cost the whole export.
    """
    faces = _faces(card)
    card_id = _card_id(card, faces)
    name = card.get("name")
    if not card_id or not name:
        return None
    values = {
        "id": card_id,
        "name": str(name),
        "mana_cost": _face_value(card, faces, "mana_cost"),
        "cmc": _cmc(card),
        "type_line": _face_value(card, faces, "type_line"),
        "oracle_text": _face_value(card, faces, "oracle_text"),
        "power": _face_value(card, faces, "power"),
        "toughness": _face_value(card, faces, "toughness"),
        "loyalty": _face_value(card, faces, "loyalty"),
        "colors": _color_list(card, faces, "colors"),
        "color_identity": _color_list(card, faces, "color_identity"),
        "rarity": card.get("rarity"),
        "set_code": card.get("set"),
        "set_name": card.get("set_name"),
        "layout": card.get("layout"),
        "image_uri": _image_uri(card, faces),
        "scryfall_uri": card.get("scryfall_uri"),
    }
    return tuple(values[field] for field in _FIELDS)


def _clear_temp(tmp_path: Path) -> None:
    for suffix in _TEMP_SUFFIXES:
        Path(str(tmp_path) + suffix).unlink(missing_ok=True)


def _open_temp_database(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path))
    # The temp file is disposable - it is either renamed over the real
    # database at the end or deleted - so durability guarantees on it buy
    # nothing and cost a great deal of SD-card write time on the Pi.
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    cards.create_schema(conn)
    return conn


def _load_cards(conn: sqlite3.Connection, stream: BinaryIO, report: ProgressCallback) -> int:
    """Stream newline-delimited JSON into `conn`, batching inserts in one transaction.

    Committing per row across ~30k cards means ~30k separate writes to the
    Pi's SD card; batching into a single transaction turns the whole ingest
    into one durable write at the end.

    One card per line means each record is parsed and discarded independently,
    so peak memory is one card rather than the whole export - the same property
    the old streaming array parser was there to provide, now for free.
    """
    batch: list[tuple] = []
    parsed = 0
    excluded = 0
    for lineno, line in enumerate(stream, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            card = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise IngestError(f"malformed JSON on line {lineno} of the export: {e}") from e
        if not isinstance(card, dict):
            logger.warning("skipped a non-object entry on line %d", lineno)
            continue
        if card.get("layout") in EXCLUDED_LAYOUTS:
            excluded += 1
            continue
        row = card_row(card)
        if row is None:
            logger.warning("skipped a bulk entry with no oracle id or name")
            continue
        batch.append(row)
        if len(batch) >= BATCH_SIZE:
            conn.executemany(_INSERT_SQL, batch)
            batch.clear()
        parsed += 1
        if parsed % PROGRESS_INTERVAL == 0:
            report("downloading", parsed, None)
    if batch:
        conn.executemany(_INSERT_SQL, batch)
    logger.info("ingested %d cards, excluded %d non-playable entries", parsed, excluded)
    report("finalizing", parsed, parsed)
    conn.commit()
    # Counted off the table rather than the loop: OR REPLACE collapses any
    # duplicate oracle_id, so the row count is the only honest answer.
    return conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]


def ingest_stream(
    stream: BinaryIO, db_path: Path, progress: ProgressCallback | None = None
) -> int:
    """Parse a decompressed JSONL export off `stream` into `db_path`.

    Returns cards written. Split out from ingest() so the parse/insert path is
    exercisable against a fixture without touching the network; `stream` is
    already-decompressed bytes, so gzip handling stays in ingest() where the
    transport lives.
    """
    db_path = Path(db_path)
    tmp_path = db_path.with_name(db_path.name + ".tmp")
    report = progress or _ignore_progress

    db_path.parent.mkdir(parents=True, exist_ok=True)
    _clear_temp(tmp_path)

    written = 0
    succeeded = False
    try:
        with closing(_open_temp_database(tmp_path)) as conn:
            written = _load_cards(conn, stream, report)
        # The connection is closed by this point on purpose: Windows refuses
        # to replace a file that still has an open handle, and the dev machine
        # is Windows even though the appliance is not.
        os.replace(tmp_path, db_path)
        succeeded = True
    except IngestError:
        raise
    except (OSError, EOFError, sqlite3.Error) as e:
        # EOFError is gzip's truncated-stream signal, which a dropped
        # connection mid-download produces.
        raise IngestError(f"failed to build the card database: {e}") from e
    finally:
        # Anything short of a completed rename - a parse error, a dropped
        # connection, Ctrl-C - would otherwise leave the temp file for the
        # next run to trip over, so it goes however we left.
        if not succeeded:
            _clear_temp(tmp_path)

    report("done", written, written)
    return written


def ingest(db_path: Path, progress: ProgressCallback | None = None) -> int:
    """Download the Oracle Cards export and rebuild `db_path`. Returns cards written."""
    report = progress or _ignore_progress
    report("discovering", 0, None)
    download_uri = bulk_download_uri()
    report("downloading", 0, None)
    # Scryfall serves the export as a gzip *file* (Content-Type
    # application/gzip), not as a gzip-encoded response, so urllib hands back
    # compressed bytes and this has to inflate them itself. Wrapping the live
    # socket rather than downloading first keeps peak disk use to the database
    # being built, instead of that plus a ~140 MB scratch copy.
    with _open_url(download_uri, DOWNLOAD_TIMEOUT) as response:
        with gzip.GzipFile(fileobj=response) as stream:
            return ingest_stream(stream, db_path, progress)


def _print_progress(stage: str, done: int, total: int | None) -> None:
    print(f"{stage}: {done}" + (f"/{total}" if total is not None else ""), flush=True)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    try:
        written = ingest(db_path, _print_progress)
    except IngestError as e:
        print(f"ingest failed: {e}", file=sys.stderr)
        return 1
    print(f"wrote {written} cards to {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
