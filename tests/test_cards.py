import gzip
import io
import json
import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from mtgkiosk import cards
from mtgkiosk import ingest as ingest_cards

# Fixtures mirror the real Scryfall bulk-export shape, including the parts that
# are easy to get wrong: a transform card whose printed values live on
# card_faces and whose top-level mana_cost is an empty string rather than
# absent, and a card carrying no image_uris at all.

LLANOWAR_ELVES = {
    "object": "card",
    "oracle_id": "llanowar-oracle-id",
    "id": "llanowar-printing-id",
    "name": "Llanowar Elves",
    "layout": "normal",
    "mana_cost": "{G}",
    "cmc": 1.0,
    "type_line": "Creature — Elf Druid",
    "oracle_text": "{T}: Add {G}.",
    "power": "1",
    "toughness": "1",
    "colors": ["G"],
    "color_identity": ["G"],
    "rarity": "common",
    "set": "m19",
    "set_name": "Core Set 2019",
    "image_uris": {"normal": "https://cards.example.invalid/llanowar.jpg"},
    "scryfall_uri": "https://scryfall.example.invalid/llanowar-elves",
}

DELVER_OF_SECRETS = {
    "object": "card",
    "oracle_id": "delver-oracle-id",
    "name": "Delver of Secrets // Insectile Aberration",
    "layout": "transform",
    "mana_cost": "",
    "cmc": 1.0,
    "type_line": "Creature — Human Wizard // Creature — Human Insect",
    "color_identity": ["U"],
    "rarity": "common",
    "set": "isd",
    "set_name": "Innistrad",
    "scryfall_uri": "https://scryfall.example.invalid/delver-of-secrets",
    "card_faces": [
        {
            "name": "Delver of Secrets",
            "mana_cost": "{U}",
            "type_line": "Creature — Human Wizard",
            "oracle_text": "At the beginning of your upkeep, look at the top card of your library.",
            "power": "1",
            "toughness": "1",
            "colors": ["U"],
            "image_uris": {"normal": "https://cards.example.invalid/delver-front.jpg"},
        },
        {
            "name": "Insectile Aberration",
            "mana_cost": "",
            "type_line": "Creature — Human Insect",
            "oracle_text": "Flying",
            "power": "3",
            "toughness": "2",
            "colors": ["U"],
        },
    ],
}

ARTLESS_ODDITY = {
    "object": "card",
    "oracle_id": "artless-oracle-id",
    "name": "Artless Oddity",
    "layout": "normal",
    "mana_cost": "{1}",
    "cmc": 1.0,
    "type_line": "Artifact",
    "oracle_text": "",
    "colors": [],
    "color_identity": [],
    "rarity": "rare",
    "set": "tst",
    "set_name": "Test Set",
    "scryfall_uri": "https://scryfall.example.invalid/artless-oddity",
}

BULK_FIXTURE = [LLANOWAR_ELVES, DELVER_OF_SECRETS, ARTLESS_ODDITY]


def _ingest(tmp_path: Path, db_path: Path, entries: list[dict], progress=None) -> int:
    source = tmp_path / "bulk.jsonl"
    source.write_text(
        "\n".join(json.dumps(entry) for entry in entries), encoding="utf-8"
    )
    with source.open("rb") as stream:
        return ingest_cards.ingest_stream(stream, db_path, progress)


def _ingest_bytes(tmp_path: Path, db_path: Path, raw: bytes) -> int:
    source = tmp_path / "bulk.json"
    source.write_bytes(raw)
    with source.open("rb") as stream:
        return ingest_cards.ingest_stream(stream, db_path)


def _build_db(db_path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(str(db_path))
    cards.create_schema(conn)
    for row in rows:
        columns = ", ".join(row)
        placeholders = ", ".join(["?"] * len(row))
        conn.execute(f"INSERT INTO cards ({columns}) VALUES ({placeholders})", tuple(row.values()))
    conn.commit()
    conn.close()


def _creature(card_id: str, name: str, type_line: str) -> dict:
    return {"id": card_id, "name": name, "type_line": type_line}


def _fake_response(payload) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def _gzipped_jsonl(entries: list[dict]) -> io.BytesIO:
    """Scryfall serves the export as a gzip file, not a gzip-encoded response."""
    body = "\n".join(json.dumps(entry) for entry in entries).encode("utf-8")
    return io.BytesIO(gzip.compress(body))


# --- ingest -----------------------------------------------------------------


def test_ingest_writes_every_card_in_the_export(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    written = _ingest(tmp_path, db_path, BULK_FIXTURE)
    assert written == 3
    assert cards.count(db_path) == 3


def test_ingest_maps_a_normal_creature_onto_the_schema(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, BULK_FIXTURE)

    card = cards.get(db_path, "llanowar-oracle-id")
    assert card.name == "Llanowar Elves"
    assert card.mana_cost == "{G}"
    assert card.type_line == "Creature — Elf Druid"
    assert card.oracle_text == "{T}: Add {G}."
    assert (card.power, card.toughness) == ("1", "1")
    assert card.set_code == "m19"
    assert card.set_name == "Core Set 2019"
    assert card.image_uri == "https://cards.example.invalid/llanowar.jpg"


def test_ingest_stores_cmc_as_a_float(tmp_path):
    # cmc is coerced because the column is REAL while Scryfall reports whole
    # costs as ints and half-costs as floats.
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, BULK_FIXTURE)
    assert cards.get(db_path, "llanowar-oracle-id").cmc == 1.0


def test_ingest_joins_colors_with_commas(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    azorius = dict(LLANOWAR_ELVES, oracle_id="azorius-id", name="Azorius Thing", colors=["W", "U"], color_identity=["W", "U"])
    _ingest(tmp_path, db_path, [azorius])

    card = cards.get(db_path, "azorius-id")
    assert card.colors == "W,U"
    assert card.color_identity == "W,U"


def test_ingest_flattens_double_faced_oracle_text(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, BULK_FIXTURE)

    card = cards.get(db_path, "delver-oracle-id")
    assert card.oracle_text == (
        "At the beginning of your upkeep, look at the top card of your library.\n//\nFlying"
    )


def test_ingest_flattens_double_faced_power_and_toughness(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, BULK_FIXTURE)

    card = cards.get(db_path, "delver-oracle-id")
    assert card.power == "1\n//\n3"
    assert card.toughness == "1\n//\n2"


def test_ingest_treats_an_empty_top_level_mana_cost_as_absent(tmp_path):
    # Transform cards carry "mana_cost": "" at top level with the real cost on
    # face 0; taking the empty string at face value would blank every one.
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, BULK_FIXTURE)
    assert cards.get(db_path, "delver-oracle-id").mana_cost == "{U}"


def test_ingest_unions_double_faced_colors_rather_than_joining_them(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, BULK_FIXTURE)
    assert cards.get(db_path, "delver-oracle-id").colors == "U"


def test_ingest_falls_back_to_the_first_face_image(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, BULK_FIXTURE)
    assert cards.get(db_path, "delver-oracle-id").image_uri == (
        "https://cards.example.invalid/delver-front.jpg"
    )


def test_ingest_stores_null_image_uri_for_a_card_with_no_images(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, BULK_FIXTURE)

    card = cards.get(db_path, "artless-oracle-id")
    assert card.image_uri is None
    assert card.to_dict()["has_image"] is False


def test_ingest_does_not_fail_over_a_card_with_no_image(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    assert _ingest(tmp_path, db_path, [ARTLESS_ODDITY]) == 1


def test_ingest_uses_the_first_face_oracle_id_when_the_top_level_one_is_missing(tmp_path):
    # reversible_card layouts omit the top-level oracle_id and put one per face.
    reversible = {
        "name": "Reversible Thing",
        "layout": "reversible_card",
        "card_faces": [
            {"name": "Front", "oracle_id": "face-zero-oracle-id", "oracle_text": "Front text"},
            {"name": "Back", "oracle_id": "face-one-oracle-id", "oracle_text": "Back text"},
        ],
    }
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, [reversible])
    assert cards.get(db_path, "face-zero-oracle-id").name == "Reversible Thing"


def test_ingest_skips_an_entry_with_no_id_or_name(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    written = _ingest(tmp_path, db_path, [*BULK_FIXTURE, {"layout": "normal"}])
    assert written == 3


def test_ingest_replaces_an_existing_database(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [{"id": "stale", "name": "Stale Card"}])

    _ingest(tmp_path, db_path, BULK_FIXTURE)

    assert cards.count(db_path) == 3
    assert cards.get(db_path, "stale") is None


def test_ingest_creates_the_data_directory_when_missing(tmp_path):
    db_path = tmp_path / "data" / "cards.sqlite"
    assert _ingest(tmp_path, db_path, BULK_FIXTURE) == 3
    assert db_path.exists()


def test_failed_ingest_leaves_an_existing_database_intact(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [{"id": "keep-me", "name": "Existing Card"}])

    # Valid card first, then a line cut off mid-object: the failure lands
    # after rows have already been written to the temp database.
    truncated = (json.dumps(LLANOWAR_ELVES) + '\n{"name": "Half A').encode("utf-8")
    with pytest.raises(ingest_cards.IngestError):
        _ingest_bytes(tmp_path, db_path, truncated)

    assert cards.count(db_path) == 1
    assert cards.get(db_path, "keep-me").name == "Existing Card"
    assert cards.get(db_path, "llanowar-oracle-id") is None


def test_failed_ingest_removes_the_temporary_database(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    with pytest.raises(ingest_cards.IngestError):
        _ingest_bytes(tmp_path, db_path, b'{"name": "Half A')
    assert not (tmp_path / "cards.sqlite.tmp").exists()


def test_failed_ingest_does_not_create_a_database_that_was_not_there(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    with pytest.raises(ingest_cards.IngestError):
        _ingest_bytes(tmp_path, db_path, b'{"name": "Half A')
    assert not db_path.exists()
    assert cards.is_available(db_path) is False


def test_ingest_overwrites_a_leftover_temporary_file_from_a_crashed_run(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    leftover = tmp_path / "cards.sqlite.tmp"
    leftover.write_bytes(b"not a database, just debris from a killed run")

    assert _ingest(tmp_path, db_path, BULK_FIXTURE) == 3
    assert not leftover.exists()


def test_ingest_writes_every_card_when_the_batch_size_does_not_divide_evenly(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_cards, "BATCH_SIZE", 2)
    entries = [dict(LLANOWAR_ELVES, oracle_id=f"card-{i}", name=f"Card {i}") for i in range(5)]

    db_path = tmp_path / "cards.sqlite"
    assert _ingest(tmp_path, db_path, entries) == 5


def test_progress_is_reported_at_an_interval_rather_than_per_card(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_cards, "PROGRESS_INTERVAL", 2)
    entries = [dict(LLANOWAR_ELVES, oracle_id=f"card-{i}", name=f"Card {i}") for i in range(5)]

    events = []
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, entries, progress=lambda stage, done, total: events.append((stage, done, total)))

    assert [e for e in events if e[0] == "downloading"] == [("downloading", 2, None), ("downloading", 4, None)]
    assert events[-2:] == [("finalizing", 5, 5), ("done", 5, 5)]


def test_ingest_without_a_progress_callback_still_works(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    assert _ingest(tmp_path, db_path, BULK_FIXTURE, progress=None) == 3


# --- bulk-data discovery ----------------------------------------------------


def test_bulk_download_uri_selects_the_oracle_cards_entry():
    payload = {
        "data": [
            {"type": "default_cards", "download_uri": "https://data.example.invalid/default.json"},
            {"type": "oracle_cards", "download_uri": "https://data.example.invalid/oracle.json"},
            {"type": "all_cards", "download_uri": "https://data.example.invalid/all.json"},
        ]
    }
    with patch("mtgkiosk.ingest.urllib.request.urlopen", return_value=_fake_response(payload)):
        assert ingest_cards.bulk_download_uri() == "https://data.example.invalid/oracle.json"


def test_bulk_download_uri_prefers_the_jsonl_export():
    # Scryfall moved the export to gzipped JSONL and advertises it under a
    # different key; taking download_uri when both are present would parse the
    # wrong format.
    payload = {
        "data": [
            {
                "type": "oracle_cards",
                "download_uri": "https://data.example.invalid/oracle.json",
                "jsonl_download_uri": "https://data.example.invalid/oracle.jsonl.gz",
            }
        ]
    }
    with patch("mtgkiosk.ingest.urllib.request.urlopen", return_value=_fake_response(payload)):
        assert ingest_cards.bulk_download_uri() == "https://data.example.invalid/oracle.jsonl.gz"


def test_bulk_download_uri_identifies_the_client_to_scryfall():
    payload = {"data": [{"type": "oracle_cards", "download_uri": "https://data.example.invalid/oracle.json"}]}
    with patch("mtgkiosk.ingest.urllib.request.urlopen", return_value=_fake_response(payload)) as mock_urlopen:
        ingest_cards.bulk_download_uri()

    request = mock_urlopen.call_args.args[0]
    assert request.full_url == ingest_cards.BULK_DATA_URL
    assert "mtg-kiosk" in request.get_header("User-agent")


def test_bulk_download_uri_raises_when_the_oracle_cards_entry_is_absent():
    payload = {"data": [{"type": "default_cards", "download_uri": "https://data.example.invalid/default.json"}]}
    with patch("mtgkiosk.ingest.urllib.request.urlopen", return_value=_fake_response(payload)):
        with pytest.raises(ingest_cards.IngestError):
            ingest_cards.bulk_download_uri()


def test_bulk_download_uri_raises_ingest_error_when_the_network_is_down():
    with patch("mtgkiosk.ingest.urllib.request.urlopen", side_effect=urllib.error.URLError("no route to host")):
        with pytest.raises(ingest_cards.IngestError):
            ingest_cards.bulk_download_uri()


def test_bulk_download_uri_raises_ingest_error_on_malformed_json():
    with patch("mtgkiosk.ingest.urllib.request.urlopen", return_value=io.BytesIO(b"<html>nope</html>")):
        with pytest.raises(ingest_cards.IngestError):
            ingest_cards.bulk_download_uri()


def test_ingest_downloads_the_uri_it_discovered(tmp_path):
    index = {"data": [{"type": "oracle_cards", "download_uri": "https://data.example.invalid/oracle.json"}]}
    responses = [_fake_response(index), _gzipped_jsonl(BULK_FIXTURE)]

    db_path = tmp_path / "cards.sqlite"
    with patch("mtgkiosk.ingest.urllib.request.urlopen", side_effect=responses) as mock_urlopen:
        written = ingest_cards.ingest(db_path)

    assert written == 3
    assert mock_urlopen.call_args_list[1].args[0].full_url == "https://data.example.invalid/oracle.json"


# --- query layer ------------------------------------------------------------


def test_count_returns_zero_for_a_missing_database(tmp_path):
    assert cards.count(tmp_path / "absent.sqlite") == 0


def test_is_available_is_false_for_a_missing_database(tmp_path):
    assert cards.is_available(tmp_path / "absent.sqlite") is False


def test_count_returns_zero_for_a_file_that_is_not_a_database(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    db_path.write_bytes(b"this is not sqlite")
    assert cards.count(db_path) == 0


def test_is_available_is_true_once_cards_are_present(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [{"id": "a", "name": "Ancestral Recall"}])
    assert cards.is_available(db_path) is True


def test_search_ranks_exact_then_prefix_then_substring(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [
        {"id": "1", "name": "Aftershock"},
        {"id": "2", "name": "Shocking Grasp"},
        {"id": "3", "name": "Shock"},
        {"id": "4", "name": "Shocker"},
    ])

    assert [c.name for c in cards.search(db_path, "Shock")] == [
        "Shock",
        "Shocker",
        "Shocking Grasp",
        "Aftershock",
    ]


def test_search_returns_nothing_for_a_blank_query(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [{"id": "1", "name": "Shock"}])
    assert cards.search(db_path, "   ") == []


def test_search_returns_nothing_when_the_database_is_missing(tmp_path):
    assert cards.search(tmp_path / "absent.sqlite", "Shock") == []


def test_search_escapes_percent_so_it_matches_literally(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [{"id": "1", "name": "100% Damage"}, {"id": "2", "name": "1000 Damage"}])
    assert [c.name for c in cards.search(db_path, "100%")] == ["100% Damage"]


def test_search_escapes_underscore_so_it_matches_literally(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [{"id": "1", "name": "A_B"}, {"id": "2", "name": "AXB"}])
    assert [c.name for c in cards.search(db_path, "A_B")] == ["A_B"]


def test_search_respects_the_limit(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [{"id": str(i), "name": f"Shock {i}"} for i in range(10)])
    assert len(cards.search(db_path, "Shock", limit=3)) == 3


def test_get_returns_none_for_an_unknown_id(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [{"id": "known", "name": "Shock"}])
    assert cards.get(db_path, "unknown") is None


def test_get_returns_the_card_for_a_known_id(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [{"id": "known", "name": "Shock", "mana_cost": "{R}"}])

    card = cards.get(db_path, "known")
    assert (card.name, card.mana_cost) == ("Shock", "{R}")


def test_random_card_raises_when_the_database_is_absent(tmp_path):
    with pytest.raises(cards.CardDatabaseError):
        cards.random_card(tmp_path / "absent.sqlite")


def test_random_card_returns_a_card_when_the_database_is_present(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [{"id": "only", "name": "Black Lotus"}])
    assert cards.random_card(db_path).name == "Black Lotus"


def test_creatures_by_subtype_matches_whole_subtypes(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [
        _creature("1", "Llanowar Elves", "Creature — Elf Druid"),
        _creature("2", "Elvish Mystic", "Creature — Elf"),
        _creature("3", "Loxodon Warhammer Bearer", "Creature — Elephant Soldier"),
        _creature("4", "Grizzly Bears", "Creature — Bear"),
        _creature("5", "Elvish Promenade", "Tribal Instant — Elf"),
    ])

    # Sorted here rather than asserting the query's own order: this test is
    # about which cards match, and creatures_by_subtype deliberately orders by
    # id so that `limit` doesn't hand back only the alphabetically-first slice.
    assert sorted(c.name for c in cards.creatures_by_subtype(db_path, "Elf")) == [
        "Elvish Mystic",
        "Llanowar Elves",
    ]


def test_creatures_by_subtype_returns_nothing_when_the_database_is_missing(tmp_path):
    assert cards.creatures_by_subtype(tmp_path / "absent.sqlite", "Elf") == []


def test_subtypes_with_counts_respects_the_minimum(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _build_db(db_path, [
        _creature("1", "Elf One", "Creature — Elf Warrior"),
        _creature("2", "Elf Two", "Creature — Elf Warrior"),
        _creature("3", "Elf Three", "Creature — Elf"),
        _creature("4", "Goblin One", "Creature — Goblin"),
        _creature("5", "An Artifact", "Artifact"),
    ])

    assert cards.subtypes_with_counts(db_path, minimum=2) == [("Elf", 3), ("Warrior", 2)]


def test_subtypes_with_counts_returns_nothing_when_the_database_is_missing(tmp_path):
    assert cards.subtypes_with_counts(tmp_path / "absent.sqlite") == []


def test_ingested_cards_are_searchable(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, BULK_FIXTURE)
    assert [c.name for c in cards.search(db_path, "Llanowar")] == ["Llanowar Elves"]


def test_ingested_double_faced_card_is_found_by_its_first_face_subtype(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    _ingest(tmp_path, db_path, BULK_FIXTURE)
    assert [c.name for c in cards.creatures_by_subtype(db_path, "Wizard")] == [
        "Delver of Secrets // Insectile Aberration"
    ]


# --- non-playable layouts ---------------------------------------------------


def _layout_entry(oracle_id: str, name: str, layout: str) -> dict:
    return {"oracle_id": oracle_id, "name": name, "layout": layout, "type_line": "Card"}


def test_ingest_excludes_art_series_and_token_layouts(tmp_path):
    db_path = tmp_path / "cards.sqlite"
    written = _ingest(tmp_path, db_path, [
        LLANOWAR_ELVES,
        _layout_entry("art-1", "Delver of Secrets // Delver of Secrets", "art_series"),
        _layout_entry("tok-1", "Zombie", "token"),
        _layout_entry("emb-1", "Koth of the Hammer Emblem", "emblem"),
        _layout_entry("van-1", "Titania", "vanguard"),
        _layout_entry("sch-1", "What's Yours Is Now Mine", "scheme"),
        _layout_entry("pln-1", "Strixhaven", "planar"),
        _layout_entry("fro-1", "Surprise!", "front_card"),
        _layout_entry("dft-1", "Zombie", "double_faced_token"),
    ])
    assert written == 1
    assert [c.name for c in cards.search(db_path, "Zombie")] == []
    assert cards.get(db_path, "llanowar-oracle-id") is not None


def test_ingest_keeps_playable_multi_face_layouts(tmp_path):
    # transform/split/adventure are real cards and must survive the same filter
    # that removes art series and tokens.
    db_path = tmp_path / "cards.sqlite"
    written = _ingest(tmp_path, db_path, [
        DELVER_OF_SECRETS,
        _layout_entry("split-1", "Fire // Ice", "split"),
        _layout_entry("adv-1", "Bonecrusher Giant // Stomp", "adventure"),
        _layout_entry("saga-1", "History of Benalia", "saga"),
    ])
    assert written == 4
