"""Local card database: schema, queries, and the Card record everything else uses.

Backed by SQLite built from Scryfall's Oracle Cards bulk export (see
scripts/ingest_cards.py). The database is generated, never committed - a
missing database is a normal state the UI is expected to handle, not an
error condition, so is_available()/count() never raise.

Every function opens its own short-lived connection. FastAPI runs sync route
handlers in a threadpool, and sharing one sqlite3 connection across threads is
a correctness hazard; connections against a local file are cheap enough that
pooling would be premature.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    mana_cost      TEXT,
    cmc            REAL,
    type_line      TEXT,
    oracle_text    TEXT,
    power          TEXT,
    toughness      TEXT,
    loyalty        TEXT,
    colors         TEXT,
    color_identity TEXT,
    rarity         TEXT,
    set_code       TEXT,
    set_name       TEXT,
    layout         TEXT,
    image_uri      TEXT,
    art_crop_uri   TEXT,
    scryfall_uri   TEXT
);
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_type_line ON cards(type_line);
"""

_COLUMNS = (
    "id, name, mana_cost, cmc, type_line, oracle_text, power, toughness, "
    "loyalty, colors, color_identity, rarity, set_code, set_name, layout, "
    "image_uri, art_crop_uri, scryfall_uri"
)


class CardDatabaseError(Exception):
    pass


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    mana_cost: str | None = None
    cmc: float | None = None
    type_line: str | None = None
    oracle_text: str | None = None
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None
    colors: str | None = None
    color_identity: str | None = None
    rarity: str | None = None
    set_code: str | None = None
    set_name: str | None = None
    layout: str | None = None
    image_uri: str | None = None
    # Just the artwork, no frame or text. The print path uses this rather than
    # the full card: a whole card scaled to a 2in label puts its rules text at
    # about 11 dots, below the 16-dot floor already found to print as a smudge.
    art_crop_uri: str | None = None
    scryfall_uri: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["has_image"] = bool(self.image_uri)
        return data


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _row_to_card(row: sqlite3.Row) -> Card:
    return Card(**{key: row[key] for key in row.keys()})


def _escape_like(term: str) -> str:
    """Neutralise LIKE's wildcards so a search term matches literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def is_available(db_path: Path) -> bool:
    """True when the database exists, has the schema, and holds at least one card."""
    return count(db_path) > 0


def count(db_path: Path) -> int:
    """Number of cards, or 0 for any reason the database can't be used.

    Deliberately swallows errors: a missing or half-written database is a
    normal state on a fresh install, and the caller's job is to offer a
    download, not to surface a stack trace.

    Probes the real column list rather than just COUNT(*), because a `cards`
    table with the wrong columns answers COUNT(*) perfectly happily and then
    makes every actual query raise. Without this probe the status endpoint
    reports a healthy database and the horde tribe list populates, and then
    the feature 500s the moment someone taps it - with no signal telling the
    UI to offer a rebuild. Any future column added to SCHEMA puts every
    already-deployed Pi in exactly that state until it refreshes.
    """
    path = Path(db_path)
    if not path.exists():
        return 0
    try:
        with closing(_connect(path)) as conn:
            conn.execute(f"SELECT {_COLUMNS} FROM cards LIMIT 1").fetchone()
            return conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    except sqlite3.Error:
        return 0


def _require(db_path: Path) -> Path:
    path = Path(db_path)
    if not is_available(path):
        raise CardDatabaseError("card database is not available")
    return path


def random_card(db_path: Path) -> Card:
    path = _require(db_path)
    with closing(_connect(path)) as conn:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM cards ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    if row is None:
        raise CardDatabaseError("card database is empty")
    return _row_to_card(row)


def get(db_path: Path, card_id: str) -> Card | None:
    path = Path(db_path)
    if not is_available(path):
        return None
    with closing(_connect(path)) as conn:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
    return _row_to_card(row) if row else None


def search(db_path: Path, query: str, limit: int = 25) -> list[Card]:
    """Name search, ranked exact > prefix > substring, alphabetical within each group.

    Users type few characters on an on-screen keyboard, so a prefix hit must
    never be buried under an incidental substring hit from a longer name.
    """
    term = query.strip()
    if not term:
        return []
    path = Path(db_path)
    if not is_available(path):
        return []
    # LIKE is case-insensitive for ASCII in SQLite by default.
    escaped = _escape_like(term)
    with closing(_connect(path)) as conn:
        # The rank expression stays in ORDER BY rather than the select list:
        # every selected column is fed straight into Card(), so an extra one
        # would have to be filtered back out again.
        rows = conn.execute(
            f"""
            SELECT {_COLUMNS}
            FROM cards
            WHERE name LIKE ? ESCAPE '\\'
            ORDER BY
                CASE
                    WHEN name = ? COLLATE NOCASE THEN 0
                    WHEN name LIKE ? ESCAPE '\\' THEN 1
                    ELSE 2
                END,
                name
            LIMIT ?
            """,
            (f"%{escaped}%", term, f"{escaped}%", limit),
        ).fetchall()
    return [_row_to_card(row) for row in rows]


def creatures_by_subtype(db_path: Path, subtype: str, limit: int = 500) -> list[Card]:
    """Creature cards whose type line carries the given subtype, e.g. "Zombie".

    Matches the subtype as a whole word after the em dash so "Zombie" doesn't
    also pull in "Zombie Giant" spellings from unrelated type lines, while
    still allowing the multi-subtype case ("Creature - Zombie Wizard").

    Ordered by id rather than name because `limit` truncates the pool, and the
    ids are UUIDs: a popular subtype like Human has thousands of creatures, and
    ordering by name would hand back only the alphabetically-first slice, so
    every generated horde would be full of cards beginning with A.
    """
    name = subtype.strip()
    if not name:
        return []
    path = Path(db_path)
    if not is_available(path):
        return []
    # Escaped like search() does. The subtype arrives from a request body, and
    # while the value is bound rather than interpolated, an unescaped "%" is
    # still a wildcard to LIKE - it returned a 60-card "deck" spanning every
    # tribe in Magic, reported back as subtype "%".
    escaped = _escape_like(name)
    with closing(_connect(path)) as conn:
        rows = conn.execute(
            f"""
            SELECT {_COLUMNS} FROM cards
            WHERE type_line LIKE '%Creature%'
              AND (
                  type_line LIKE ? ESCAPE '\\'
                  OR type_line LIKE ? ESCAPE '\\'
                  OR type_line = ?
              )
            ORDER BY id
            LIMIT ?
            """,
            (f"% {escaped} %", f"% {escaped}", name, limit),
        ).fetchall()
    return [_row_to_card(row) for row in rows]


def subtypes_with_counts(db_path: Path, minimum: int = 40) -> list[tuple[str, int]]:
    """Creature subtypes with at least `minimum` cards, most common first.

    Used to offer horde-mode tribes that actually have enough cards to fill a
    deck. Parsed in Python rather than SQL because the subtype list lives in
    the free-text portion of type_line after the em dash.
    """
    path = Path(db_path)
    if not is_available(path):
        return []
    counts: dict[str, int] = {}
    with closing(_connect(path)) as conn:
        rows = conn.execute(
            "SELECT type_line FROM cards WHERE type_line LIKE '%Creature%'"
        ).fetchall()
    for row in rows:
        type_line = row["type_line"] or ""
        # The first face only, and only the portion after the em dash, which is
        # where subtypes live.
        #
        # That face must itself be a creature. The SQL matches any card whose
        # *whole* type line mentions Creature, which for a transforming Saga -
        # "Enchantment — Saga // Enchantment Creature — Human Monk" - harvested
        # "Saga" as a creature subtype. There are 50 of those, over the
        # threshold, so "Saga" was offered as a horde tribe and built a deck
        # more than half of which wasn't a creature on the visible face.
        first_face = type_line.split("//")[0]
        if "Creature" not in first_face or "—" not in first_face:
            continue
        for token in first_face.split("—", 1)[1].split():
            counts[token] = counts.get(token, 0) + 1
    return sorted(
        ((name, n) for name, n in counts.items() if n >= minimum),
        key=lambda pair: (-pair[1], pair[0]),
    )
