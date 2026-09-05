import json
import random
import sqlite3

import pytest

from mtgkiosk.cards import CardDatabaseError, create_schema
from mtgkiosk.horde import DIFFICULTIES, MINIMUM_POOL, HordeError, available_subtypes, build_deck

# cards.subtypes_with_counts() splits type lines on this exact character, so the
# fixtures have to carry a real em dash rather than a hyphen.
EM_DASH = "—"


def _creature(subtype, index, cmc=2.0, extra_subtype=None):
    subtypes = subtype if extra_subtype is None else f"{subtype} {extra_subtype}"
    return (
        f"{subtype.lower()}-{index}",
        f"{subtype} {index:03d}",
        cmc,
        f"Creature {EM_DASH} {subtypes}",
    )


def _creatures(subtype, count, cmc=2.0, start=0):
    return [_creature(subtype, i, cmc=cmc) for i in range(start, start + count)]


def _make_db(tmp_path, rows, name="cards.sqlite"):
    db_path = tmp_path / name
    conn = sqlite3.connect(str(db_path))
    create_schema(conn)
    conn.executemany("INSERT INTO cards (id, name, cmc, type_line) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return db_path


def _playable_db(tmp_path):
    """A database with a comfortably playable Zombie pool."""
    return _make_db(tmp_path, _creatures("Zombie", 100))


@pytest.mark.parametrize("difficulty", ["easy", "normal", "hard"])
def test_deck_size_matches_difficulty(tmp_path, difficulty):
    deck = build_deck(_playable_db(tmp_path), "Zombie", difficulty, rng=random.Random(1))
    assert len(deck.cards) == DIFFICULTIES[difficulty]["size"]


@pytest.mark.parametrize("difficulty", ["easy", "normal", "hard"])
def test_deck_cards_per_turn_matches_difficulty(tmp_path, difficulty):
    deck = build_deck(_playable_db(tmp_path), "Zombie", difficulty, rng=random.Random(1))
    assert deck.cards_per_turn == DIFFICULTIES[difficulty]["cards_per_turn"]


def test_deck_defaults_to_normal_difficulty(tmp_path):
    deck = build_deck(_playable_db(tmp_path), "Zombie", rng=random.Random(1))
    assert deck.difficulty == "normal"
    assert len(deck.cards) == 60
    assert deck.cards_per_turn == 2


def test_every_card_in_deck_has_the_requested_subtype(tmp_path):
    db_path = _make_db(
        tmp_path,
        _creatures("Zombie", 50) + _creatures("Goblin", 50) + _creatures("Elf", 50),
    )
    deck = build_deck(db_path, "Zombie", rng=random.Random(7))
    assert all("Zombie" in card.type_line for card in deck.cards)
    assert not any(card.name.startswith(("Goblin", "Elf")) for card in deck.cards)


def test_deck_includes_creatures_with_the_subtype_alongside_others(tmp_path):
    # "Creature - Zombie Wizard" is a Zombie and belongs in a Zombie horde.
    rows = _creatures("Zombie", 40) + [
        _creature("Zombie", 900 + i, extra_subtype="Wizard") for i in range(10)
    ]
    deck = build_deck(_make_db(tmp_path, rows), "Zombie", rng=random.Random(3))
    assert any("Wizard" in card.type_line for card in deck.cards)


def test_seeded_rng_produces_identical_decks(tmp_path):
    db_path = _playable_db(tmp_path)
    first = build_deck(db_path, "Zombie", rng=random.Random(2024))
    second = build_deck(db_path, "Zombie", rng=random.Random(2024))
    assert [card.id for card in first.cards] == [card.id for card in second.cards]


def test_different_seeds_produce_different_decks(tmp_path):
    db_path = _playable_db(tmp_path)
    first = build_deck(db_path, "Zombie", rng=random.Random(1))
    second = build_deck(db_path, "Zombie", rng=random.Random(2))
    assert [card.id for card in first.cards] != [card.id for card in second.cards]


def test_deck_without_explicit_rng_is_still_valid(tmp_path):
    deck = build_deck(_playable_db(tmp_path), "Zombie")
    assert len(deck.cards) == 60


def test_deck_contains_duplicates_because_sampling_is_with_replacement(tmp_path):
    # Pool (100) is larger than the deck (40), so duplicates can only come from
    # sampling with replacement, not from the pigeonhole principle.
    db_path = _playable_db(tmp_path)
    deck = build_deck(db_path, "Zombie", "easy", rng=random.Random(11))
    assert len(deck.cards) == 40
    assert len({card.id for card in deck.cards}) < len(deck.cards)


def test_cheap_creatures_are_favoured_over_expensive_ones(tmp_path):
    db_path = _make_db(
        tmp_path,
        _creatures("Zombie", 20, cmc=1.0) + _creatures("Zombie", 20, cmc=7.0, start=100),
    )
    deck = build_deck(db_path, "Zombie", "hard", rng=random.Random(99))
    cheap = sum(1 for card in deck.cards if card.cmc == 1.0)
    expensive = sum(1 for card in deck.cards if card.cmc == 7.0)
    # 1/(1+cmc) puts a one-drop at 4x a seven-drop, so cheap creatures should
    # dominate by a wide margin - but bombs still have to get through, since a
    # horde with no threats in it is not a horde.
    assert cheap > expensive * 2
    assert expensive > 0


def test_creatures_with_missing_cmc_are_not_crowded_out(tmp_path):
    # cmc is nullable in the schema; a NULL must not blow up the weighting.
    rows = _creatures("Zombie", 40, cmc=None)
    deck = build_deck(_make_db(tmp_path, rows), "Zombie", rng=random.Random(5))
    assert len(deck.cards) == 60


def test_unknown_difficulty_raises_horde_error(tmp_path):
    with pytest.raises(HordeError) as excinfo:
        build_deck(_playable_db(tmp_path), "Zombie", "nightmare")
    assert "nightmare" in str(excinfo.value)


def test_missing_database_raises_horde_error_not_card_database_error(tmp_path):
    with pytest.raises(HordeError) as excinfo:
        build_deck(tmp_path / "does-not-exist.sqlite", "Zombie")
    assert not isinstance(excinfo.value, CardDatabaseError)


def test_empty_database_raises_horde_error(tmp_path):
    with pytest.raises(HordeError):
        build_deck(_make_db(tmp_path, []), "Zombie")


def test_subtype_with_too_few_cards_raises_horde_error(tmp_path):
    db_path = _make_db(tmp_path, _creatures("Zombie", MINIMUM_POOL - 1))
    with pytest.raises(HordeError) as excinfo:
        build_deck(db_path, "Zombie")
    assert str(MINIMUM_POOL) in str(excinfo.value)


def test_unknown_subtype_raises_horde_error(tmp_path):
    with pytest.raises(HordeError):
        build_deck(_playable_db(tmp_path), "Sliver")


def test_available_subtypes_orders_most_common_first(tmp_path):
    db_path = _make_db(
        tmp_path,
        _creatures("Zombie", 12) + _creatures("Goblin", 8) + _creatures("Elf", 5),
    )
    assert available_subtypes(db_path, minimum=5) == [("Zombie", 12), ("Goblin", 8), ("Elf", 5)]


def test_available_subtypes_respects_minimum(tmp_path):
    db_path = _make_db(
        tmp_path,
        _creatures("Zombie", 12) + _creatures("Goblin", 8) + _creatures("Elf", 5),
    )
    assert available_subtypes(db_path, minimum=10) == [("Zombie", 12)]


def test_available_subtypes_defaults_to_the_deckbuilding_minimum(tmp_path):
    db_path = _make_db(
        tmp_path, _creatures("Zombie", MINIMUM_POOL) + _creatures("Goblin", MINIMUM_POOL - 1)
    )
    assert available_subtypes(db_path) == [("Zombie", MINIMUM_POOL)]


def test_available_subtypes_raises_horde_error_when_database_missing(tmp_path):
    with pytest.raises(HordeError) as excinfo:
        available_subtypes(tmp_path / "does-not-exist.sqlite")
    assert not isinstance(excinfo.value, CardDatabaseError)


def test_to_dict_is_json_ready(tmp_path):
    deck = build_deck(_playable_db(tmp_path), "Zombie", "easy", rng=random.Random(4))
    data = deck.to_dict()
    assert data["subtype"] == "Zombie"
    assert data["difficulty"] == "easy"
    assert data["cards_per_turn"] == 1
    assert len(data["cards"]) == 40
    assert data["cards"][0]["has_image"] is False
    json.dumps(data)
