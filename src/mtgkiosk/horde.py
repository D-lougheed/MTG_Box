"""Horde-mode deck generation.

Traditional Horde Magic is played against a deck of *token* creatures, revealing
cards until a non-token appears. Scryfall's Oracle Cards export does carry
tokens - about 990 of them - but ingest.py excludes them along with art series,
emblems, schemes and planes, because they share names with real cards and mostly
have no rules text, which made card lookup ambiguous and the random roller
unreliable. That exclusion is worth more to the other three features than
token-based decks are worth to this one.

So this implementation keeps the shape of the format and drops the token
dependency by choice: the horde deck is many copies of real creature cards
sharing one creature subtype, and it reveals a fixed number of cards per turn
instead of "until a non-token" (a rule with no stopping condition once tokens
are gone). That divergence is a decided position in the Slice 5 spec, not a gap
to be closed here.

Only deck generation lives in Python. The game loop is client-side and the
server holds no session, so a backend restart mid-game cannot lose a game.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from .cards import (
    Card,
    CardDatabaseError,
    creatures_by_subtype,
    is_available,
    subtypes_with_counts,
)

DIFFICULTIES = {
    "easy": {"size": 40, "cards_per_turn": 1},
    "normal": {"size": 60, "cards_per_turn": 2},
    "hard": {"size": 80, "cards_per_turn": 3},
}

# A deck sampled with replacement can be filled from any non-empty pool, but a
# horde built from a handful of distinct creatures plays as the same card over
# and over. 40 is the floor for a deck that still feels varied at the largest
# (80-card) difficulty, and available_subtypes() defaults to the same number so
# the UI can never offer a subtype that build_deck() would then reject.
MINIMUM_POOL = 40

# 13 subtypes on the real database exceed this, so the pool genuinely is
# truncated for the popular tribes. creatures_by_subtype() orders by id (a
# UUID) precisely so that truncation samples the pool rather than biasing it -
# it used to order by name, which made a Human horde entirely cards beginning
# with "A". 500 distinct creatures is already far more variety than an 80-card
# deck can show, and loading every Human into memory to shuffle would cost real
# memory on the Pi for a difference no player would notice.
POOL_LIMIT = 500


class HordeError(Exception):
    pass


@dataclass(frozen=True)
class HordeDeck:
    subtype: str
    difficulty: str
    cards_per_turn: int
    cards: list[Card]

    def to_dict(self) -> dict:
        return {
            "subtype": self.subtype,
            "difficulty": self.difficulty,
            "cards_per_turn": self.cards_per_turn,
            "cards": [card.to_dict() for card in self.cards],
        }


def _require_database(db_path: Path) -> Path:
    path = Path(db_path)
    if not is_available(path):
        raise HordeError(f"card database is not available at {path}")
    return path


def _weight(cmc: float | None) -> float:
    """Sampling weight for one creature, cheaper meaning more likely.

    An unweighted horde is unwinnable: a 60-card deck of real creatures reveals
    mythic dragons as often as one-drops, and the table cannot answer that. The
    weight is the reciprocal of cost, 1/(1+cmc), which makes a one-drop four
    times as likely as a seven-drop while still letting the occasional bomb
    through - that tension is the point of the format, so a steeper falloff
    (squared, or exponential) would be worse, not better, because it would
    effectively delete the top of the curve.

    A missing cmc counts as 3, the middle of a typical creature curve, so an
    incomplete row is neither favoured nor buried.
    """
    cost = 3.0 if cmc is None else max(cmc, 0.0)
    return 1.0 / (1.0 + cost)


def available_subtypes(db_path: Path, minimum: int = MINIMUM_POOL) -> list[tuple[str, int]]:
    """Creature subtypes with enough cards to build a horde, most common first.

    Raises rather than returning [] when the database is missing, so the API can
    tell "no card database yet, offer a download" apart from "database is fine,
    but nothing meets the threshold" - two states that need different UI.
    """
    path = _require_database(db_path)
    try:
        return subtypes_with_counts(path, minimum=minimum)
    except CardDatabaseError as e:
        raise HordeError(f"couldn't read creature subtypes: {e}") from e


def build_deck(
    db_path: Path,
    subtype: str,
    difficulty: str = "normal",
    rng: random.Random | None = None,
) -> HordeDeck:
    """Generate a horde deck of `subtype` creatures at the given difficulty.

    Sampled *with replacement*: duplicates are correct here. A horde deck is
    many copies of similar creatures, and the pool for a given subtype is
    usually smaller than the deck anyway.
    """
    settings = DIFFICULTIES.get(difficulty)
    if settings is None:
        known = ", ".join(sorted(DIFFICULTIES))
        raise HordeError(f"unknown difficulty {difficulty!r}; expected one of: {known}")

    path = _require_database(db_path)
    try:
        pool = creatures_by_subtype(path, subtype, limit=POOL_LIMIT)
    except CardDatabaseError as e:
        # Callers get one exception type to handle, whatever the data layer does.
        raise HordeError(f"couldn't read {subtype} creatures: {e}") from e

    if len(pool) < MINIMUM_POOL:
        raise HordeError(
            f"only {len(pool)} {subtype} creatures available, need at least "
            f"{MINIMUM_POOL} for a playable horde"
        )

    rng = rng or random.Random()
    deck = rng.choices(pool, weights=[_weight(card.cmc) for card in pool], k=settings["size"])
    # Redundant in distribution terms - choices() draws independently, so the
    # list is already in random order - but it keeps "build_deck returns a
    # shuffled deck" a property of this function rather than of how the fill
    # happens to be implemented today.
    rng.shuffle(deck)

    return HordeDeck(
        subtype=subtype,
        difficulty=difficulty,
        cards_per_turn=settings["cards_per_turn"],
        cards=deck,
    )
