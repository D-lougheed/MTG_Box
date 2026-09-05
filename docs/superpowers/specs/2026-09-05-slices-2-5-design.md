# MTG Kiosk — Slices 2-5: Cards, Life Counter, Lookup, Horde

**Date:** 2026-09-05
**Status:** Approved, in implementation
**Slices:** 2, 3, 4, 5 of 5

Slice 1 (kiosk shell, printer driver, update mechanism, wifi settings) is deployed and running on real hardware. This document specs everything remaining.

## Governing constraints (carried forward from Slice 1)

- **800x480 physical screen, ~2-point capacitive touch.** Every interactive target is at least ~44px on its shortest edge. There is no mouse, no hardware keyboard, no hover state.
- **No frontend build step.** Plain ES scripts and CSS, loaded by `<script src>` / `<link>` from `web/`. No bundler, no npm.
- **A failure in one feature must never take down the kiosk.** Same rule Slice 1 applied to the printer, now applied to the card database and network fetches.
- **Offline-first.** The Pi may have no network. Card *text* is always local; only images and the database refresh need network, and both degrade gracefully.
- **The backend binds to 127.0.0.1 only.**

## Slice 2 — Card data layer, random card, print

### Data source

Scryfall **Oracle Cards** bulk export: one entry per unique card name (no duplicate printings), ~30k cards, ~24.5 MB compressed. Chosen over Default/All Cards because every feature here is text-driven and printing-agnostic; duplicate printings would only add noise to search and skew the random roll toward heavily-reprinted cards.

The bulk endpoint is discovered at runtime rather than hardcoded: `GET https://api.scryfall.com/bulk-data`, find the entry with `type == "oracle_cards"`, use its download URI. Scryfall rotates those URIs daily, so hardcoding one guarantees eventual breakage.

**Format, verified 2026-09-05:** that entry now exposes `jsonl_download_uri` and serves **gzipped JSONL** — one card object per line, `Content-Type: application/gzip` with no `Content-Encoding`, so the client inflates it itself. The older `download_uri` (a single pretty-printed JSON array) is gone from the index. Runtime discovery protected against the rotating URI but not against the field being renamed underneath it, which is exactly how this was found: the first real ingest failed with "no usable 'oracle_cards' entry". JSONL is the easier format anyway — each line parses independently with stdlib `json`, so peak memory is one card and no streaming-parser dependency is needed.

**Not every entry is a playable card.** Art series, front cards, tokens, double-faced tokens, emblems, vanguards, schemes and planes are excluded at ingest — about 10% of the export. They mostly carry no rules text and several share a name with the real card, so including them made lookup ambiguous and the random roller unreliable. Real cards land at ~34.6k rows.

### Storage

SQLite at `data/cards.sqlite`. `data/` is already gitignored — the database is **built, never committed**.

```sql
CREATE TABLE cards (
    id            TEXT PRIMARY KEY,   -- Scryfall oracle_id
    name          TEXT NOT NULL,
    mana_cost     TEXT,
    cmc           REAL,
    type_line     TEXT,
    oracle_text   TEXT,
    power         TEXT,               -- text, not numeric: "*", "1+*" are legal
    toughness     TEXT,
    loyalty       TEXT,
    colors        TEXT,               -- comma-joined single letters, e.g. "W,U"
    color_identity TEXT,
    rarity        TEXT,
    set_code      TEXT,
    set_name      TEXT,
    layout        TEXT,
    image_uri     TEXT,               -- normal-size JPEG URL, may be NULL
    scryfall_uri  TEXT
);
CREATE INDEX idx_cards_name ON cards(name);
CREATE INDEX idx_cards_type_line ON cards(type_line);
```

No FTS5. Search is `LIKE` against 30k rows, which is a few milliseconds on a Pi 5 and avoids an extension dependency plus the shadow-table bookkeeping FTS5 needs on rebuild.

**Double-faced cards** (`layout` in `transform`, `modal_dfc`, `split`, `flip`, `adventure`): the top-level object has no `oracle_text`/`mana_cost`/`power`. Flatten `card_faces` by joining each face's fields with `\n//\n` between faces, so one row always fully represents one card. `image_uri` comes from face 0 when absent at top level.

**Cards with no image** (rare, but `image_uris` can be missing): store NULL, never fail ingest.

### Ingest

`scripts/ingest_cards.py`, also importable so the API can drive it.

Inflates the gzip stream and parses one line at a time with stdlib `json`. Peak memory is a single card rather than the ~140 MB export, which matters on a 4 GB Pi that is also running a browser.

*(This originally specified streaming a JSON array with `ijson`, which was correct until the format change above. JSONL made the dependency unnecessary — each line is independently parseable — so `ijson` was removed.)*

Writes to `data/cards.sqlite.tmp` and atomically renames over the real path on success, so an interrupted or failed ingest never leaves a half-populated database in place.

Reports progress through a callback so the API can surface it: `progress(stage: str, done: int, total: int | None)`.

### Card database module

`src/mtgkiosk/cards.py`. Every function takes an explicit `db_path` and opens a short-lived connection — FastAPI runs sync route handlers in a threadpool, and a single shared SQLite connection across threads is a correctness hazard. Connections are cheap against a local file.

```python
class CardDatabaseError(Exception): ...

@dataclass(frozen=True)
class Card:
    id: str
    name: str
    mana_cost: str | None
    cmc: float | None
    type_line: str | None
    oracle_text: str | None
    power: str | None
    toughness: str | None
    loyalty: str | None
    colors: str | None
    color_identity: str | None
    rarity: str | None
    set_code: str | None
    set_name: str | None
    layout: str | None
    image_uri: str | None
    scryfall_uri: str | None

    def to_dict(self) -> dict: ...

def is_available(db_path: Path) -> bool          # file exists, schema present, >0 rows
def count(db_path: Path) -> int                  # 0 when unavailable, never raises
def random_card(db_path: Path) -> Card           # raises CardDatabaseError when unavailable
def search(db_path: Path, query: str, limit: int = 25) -> list[Card]
def get(db_path: Path, card_id: str) -> Card | None
def creatures_by_subtype(db_path: Path, subtype: str, limit: int) -> list[Card]
def subtypes_with_counts(db_path: Path, minimum: int = 40) -> list[tuple[str, int]]
```

`search` ranks exact match first, then prefix match, then substring, each alphabetical within its group. On a kiosk with an on-screen keyboard, users type few characters, so prefix hits must not be buried under incidental substring hits.

### Print path

`src/mtgkiosk/printer/card_label.py` renders a card to a Pillow image for the existing `ThermalPrinter.print_image()`.

Canvas is **609 x 406 dots** (3in x 2in at 203 DPI), the confirmed production label. Monochrome, 1-bit. Layout, top to bottom:

- Name (bold, largest, truncated with an ellipsis if it overruns one line)
- Mana cost and type line on one row
- A horizontal rule
- Oracle text, word-wrapped, shrinking through a font-size ladder to fit; overflow truncated with an ellipsis rather than overrunning the label
- Power/toughness or loyalty, bottom-right, when present

Fonts resolve through a candidate list (Pi's DejaVu first, then common Windows faces, finally Pillow's built-in bitmap font) so tests run anywhere. Only the Pi ever prints, so a dev machine falling back to a different face is cosmetic. Tests assert layout behaviour — that it fits, wraps, and truncates — never exact pixels.

### Artwork on the label — added 2026-09-05

Slice 1 ruled that the print path never needs card art, on the grounds that a monochrome 203 DPI head can't reproduce it. Half of that holds and half doesn't, and the difference is *which* image you print.

**Printing the whole card image is worse than text alone.** A card is 3.5in tall; scaled into a 2in label it renders at 57%, putting its rules text at roughly 11 dots. This module already established 16 dots as the floor where 203 DPI thermal output stops being readable and becomes grey smudge — so a whole-card print is *less* legible than the text label it would replace, while also wasting a third of the label on white space either side of a portrait card in a landscape frame.

**Printing the artwork alone works well.** Scryfall's `art_crop` is the illustration with no frame or text. Given a 240-dot column and Floyd-Steinberg dithering it stays clearly recognisable, and the remaining 369 dots render the text at exactly the size it would get on a text-only label — verified pixel-for-pixel in tests. So `render_with_art()` puts art down the left and the same text renderer down the right.

The art is cropped to fill its column rather than fitted whole: `art_crop` is landscape and the column is portrait, so fitting would leave most of the column blank.

`art_crop_uri` is stored as its own column rather than derived by rewriting the `normal` URL's path. That rewrite happens to work, but the URL structure is undocumented and would break silently.

**Art never blocks a print.** `POST /api/cards/print` takes `art` (default true) and falls back to the text label whenever the artwork is missing, uncached and unreachable, or unreadable. At a table with no network the label still comes out; the response reports which was used.

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/cards/status` | `{available, count, updating, progress}` |
| `GET` | `/api/cards/random` | One random card |
| `GET` | `/api/cards/search?q=` | Up to 25 matches |
| `GET` | `/api/cards/{id}` | One card by oracle id |
| `POST` | `/api/cards/print` | `{id}` → prints a label |
| `POST` | `/api/cards/update` | Starts a background ingest |
| `GET` | `/api/cards/{id}/image` | Cached card image (Slice 4) |

`POST /api/cards/update` returns immediately and runs the ingest on a background thread; the UI polls `/api/cards/status` for progress. The kiosk has no terminal, so a database refresh has to be reachable from the touchscreen.

Card JSON is the `Card.to_dict()` shape above, plus `has_image: bool`.

### Random card UI

The floating dice button already exists on every screen and currently opens a stub view. It now rolls a card and shows it, with **Roll again** and **Print** actions. When the database is missing, the view says so and points at Settings rather than erroring.

## Slice 3 — Life counter

Standalone: no card data, no network, no backend. Pure frontend plus `localStorage`.

**Player counts 2-8.** Layout by count:

| Players | Grid | Rotation |
|---|---|---|
| 2 | 1 col x 2 rows | Top player rotated 180° |
| 3-4 | 2 x 2 | Top row rotated 180° |
| 5-6 | 3 x 2 | Top row rotated 180° |
| 7-8 | 4 x 2 | Top row rotated 180° |

Rotating the far side is the whole point of a table-centre device: opposing players read their own total right way up. This is the main thing that makes it "better looking than lifecounter.app" on this form factor.

**Starting life:** 20, 30, or 40, chosen at game start. 40 is the Commander default and the likely case at 5+ players.

**Per-tile interaction:** the tile's left half is -1, right half is +1, with press-and-hold auto-repeat after a short delay, accelerating. The life number itself is not a button — it opens that player's detail panel.

**Detail panel** (per player): commander damage received from each opponent (a grid of steppers, 21 is lethal and is highlighted), poison counters (10 is lethal), a name field, and a "reset this player" action.

**Game state persists to `localStorage`** on every change and restores on load. A kiosk that reboots mid-game must not lose the game.

**No timers, no history/undo log.** Both are scope creep against a device whose primary job is a number that goes up and down.

Files: `web/js/lifecounter.js`, `web/css/lifecounter.css`.

## Slice 4 — Card lookup

Search view reusing the existing on-screen keyboard component:

- Text input plus `keyboard.js`, searching as you type (debounced ~250ms)
- Results as a scrollable list of name + type line
- Tap a result for a detail view: name, mana cost, type line, oracle text, P/T or loyalty, set, rarity
- **Print** button on the detail view
- Card image loaded on demand from `/api/cards/{id}/image`

### Image cache

`src/mtgkiosk/images.py`. `GET /api/cards/{id}/image` returns the cached JPEG from `data/images/{id}.jpg`; on a miss it fetches `image_uri` from Scryfall, writes it to the cache, and serves it. Cache misses with no network return **404, never a hang** — the fetch has a short timeout, and the UI treats a missing image as normal rather than as an error.

The cache is unbounded by design: the whole Oracle set at ~100 KB per image is roughly 3 GB against a 10 GB budget, and in practice only looked-up cards are ever fetched.

Files: `src/mtgkiosk/images.py`, `web/js/cards.js` (shared with random card), `web/css/cards.css`.

## Slice 5 — Horde mode

### The rules problem, and the decision

Traditional Horde Magic is built on a physical deck of **token creatures**, and reveals cards from the horde library until a non-token is revealed.

**Corrected 2026-09-05.** This section originally claimed Scryfall's Oracle Cards export contains no tokens. That is simply wrong — it carries 911 `token` and 80 `double_faced_token` entries. What is true is that this project *deliberately excludes* them at ingest, along with art series, front cards, emblems, schemes, planes and vanguards. Those layouts are about 10% of the export, most carry no rules text, and several share a name with the real card: left in, a lookup for "Delver of Secrets" returned three rows of which one was the card, and the random roller landed on a textless art card roughly one time in sixteen.

That exclusion is worth far more to the other three features than token-based horde decks are worth to this one, and ~990 tokens across all of Magic is a thin pool to build a themed horde from in any case. So the design below stands, but on an honest footing: the token dependency is dropped **by choice**, not by absence. Reintroducing traditional horde decks would mean re-admitting tokens at ingest and giving lookup and random-card their own filters.

This implementation keeps the *shape* of Horde Magic while dropping that dependency:

- The horde deck is generated from **real creature cards of a chosen creature subtype** (Zombie, Goblin, Eldrazi, Vampire, Dinosaur, ...), with duplicates allowed, drawn from the local database.
- The horde reveals a **fixed number of cards per turn** rather than "until a non-token", since without tokens that rule has no stopping condition.
- Everything else is faithful: the horde has no life total and no hand, every horde creature attacks every turn, and the players win by surviving until the horde library and battlefield are both empty.

This is documented as a deliberate divergence, not an oversight.

### Engine split

Deck generation is Python and testable; the game loop is client-side JS with no server session state. The server never holds a game — a backend restart mid-game therefore cannot lose one, and the engine needs no session storage.

`src/mtgkiosk/horde.py`:

```python
@dataclass(frozen=True)
class HordeDeck:
    subtype: str
    difficulty: str
    cards_per_turn: int
    cards: list[Card]

def available_subtypes(db_path, minimum=40) -> list[tuple[str, int]]
def build_deck(db_path, subtype, difficulty="normal", size=60, rng=None) -> HordeDeck
```

Difficulty sets deck size and reveal rate: `easy` 40 cards / 1 per turn, `normal` 60 / 2, `hard` 80 / 3. `rng` is injectable so tests are deterministic.

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/horde/subtypes` | Playable subtypes with card counts |
| `POST` | `/api/horde/deck` | `{subtype, difficulty}` → a generated deck |

### UI

Setup (pick subtype, difficulty, player count, starting life) → game screen showing horde library remaining, the horde battlefield as a list of creatures with power/toughness, player life totals, and a **Horde turn** button that reveals the next batch. Creatures are removed by tapping them (they died). Players win when library and battlefield are both empty; the horde wins when every player is at zero.

Game state persists to `localStorage`, same as the life counter.

Files: `src/mtgkiosk/horde.py`, `web/js/horde.js`, `web/css/horde.css`.

## File ownership

Slices are implemented in parallel, so each owns a disjoint set of files. Shared files — `web/index.html`, `web/css/style.css`, `src/mtgkiosk/app.py` — are integrated centrally, not edited by feature work.

| Area | Files |
|---|---|
| Card data | `src/mtgkiosk/cards.py`, `scripts/ingest_cards.py`, `tests/test_cards.py` |
| Card printing | `src/mtgkiosk/printer/card_label.py`, `tests/test_card_label.py` |
| Images | `src/mtgkiosk/images.py`, `tests/test_images.py` |
| Horde engine | `src/mtgkiosk/horde.py`, `tests/test_horde.py` |
| Life counter UI | `web/js/lifecounter.js`, `web/css/lifecounter.css` |
| Cards UI | `web/js/cards.js`, `web/css/cards.css` |
| Horde UI | `web/js/horde.js`, `web/css/horde.css` |
| Integration | `web/index.html`, `web/css/style.css`, `src/mtgkiosk/app.py` |

## Testing strategy

- **Card data:** ingest against a small fixture JSON, not the network. Search ranking, DFC flattening, and the missing-database path all get explicit tests.
- **Card label:** rendering asserts fit/wrap/truncate behaviour on the real 609x406 canvas, never exact pixels.
- **Images:** cache hit, cache miss with a mocked fetch, and network-failure-returns-404, all without real network.
- **Horde:** deck generation with a seeded RNG; size, reveal rate, and subtype filtering are deterministic and asserted.
- **Frontend:** verified by driving the real UI in a browser at 800x480, the same way the wifi manual-entry flow was checked. No JS test runner is introduced — that would mean a build step, which the project has deliberately avoided.

## Dependencies added

**None.** `ijson` was planned for streaming the bulk export, but Scryfall's move to gzipped JSONL made stdlib `gzip` + `json` sufficient — one card per line parses independently, which is the property `ijson` was there to provide. Downloads use stdlib `urllib.request` rather than adding an HTTP client.
