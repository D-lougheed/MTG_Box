import pytest
from PIL import Image, ImageChops

from mtgkiosk.cards import Card
from mtgkiosk.printer import card_label, raster
from mtgkiosk.printer.card_label import LABEL_HEIGHT_DOTS, LABEL_WIDTH_DOTS, render


def _ink_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of the drawn (black) pixels, or None for a blank label.

    Image.getbbox() finds non-zero pixels, and in mode "1" the background is
    the non-zero value, so it has to be inverted to measure ink.
    """
    return ImageChops.invert(img.convert("L")).getbbox()


def _card(**overrides) -> Card:
    fields = {"id": "test-id", "name": "Test Card", "type_line": "Creature — Human"}
    fields.update(overrides)
    return Card(**fields)


VANILLA = _card(name="Grizzly Bears", mana_cost="{1}{G}", type_line="Creature — Bear", power="2", toughness="2")
PLANESWALKER = _card(
    name="Nicol Bolas, God-Pharaoh",
    mana_cost="{4}{U}{B}{R}",
    type_line="Legendary Planeswalker — Bolas",
    oracle_text=(
        "+2: Target opponent exiles cards from the top of their library until they "
        "exile a nonland card. Until end of turn, you may cast that card without "
        "paying its mana cost.\n"
        "+1: Each opponent exiles two cards from their hand.\n"
        "-4: Nicol Bolas, God-Pharaoh deals 7 damage to target opponent, planeswalker "
        "or creature.\n"
        "-12: Exile each nonland permanent your opponents control."
    ),
    loyalty="7",
)
LONG_NAME = _card(
    name="Ultimate Nightmare of Wizards of the Coast Customer Service",
    mana_cost="{B}{B}{B}{B}{B}{B}{B}",
    type_line="Legendary Enchantment Creature — Horror Beast",
    oracle_text="When you cast this spell, each player must make a phone call.",
    power="10",
    toughness="10",
)
DOUBLE_FACED = _card(
    name="Delver of Secrets\n//\nInsectile Aberration",
    mana_cost="{U}\n//\n",
    type_line="Creature — Human Wizard\n//\nCreature — Human Insect",
    oracle_text=(
        "At the beginning of your upkeep, look at the top card of your library. You "
        "may reveal that card. If an instant or sorcery card is revealed this way, "
        "transform Delver of Secrets.\n//\nFlying"
    ),
    power="1\n//\n3",
    toughness="1\n//\n2",
)
WALL_OF_TEXT = _card(
    name="Enter the Infinite",
    mana_cost="{8}{U}{U}{U}",
    type_line="Sorcery",
    # Far more text than any real card carries, so it overflows even the
    # smallest rung of the font ladder.
    oracle_text="Draw cards equal to the number of cards in your library. " * 20,
)
REMINDER_TEXT = _card(
    name="Serra Angel",
    mana_cost="{3}{W}{W}",
    type_line="Creature — Angel",
    oracle_text=(
        "Flying (This creature can't be blocked except by creatures with flying or "
        "reach.)\nVigilance (Attacking doesn't cause this creature to tap.)"
    ),
    power="4",
    toughness="4",
)
BARE_LAND = _card(name="Wastes", mana_cost="", type_line="Basic Land", oracle_text=None)

ALL_CARDS = [VANILLA, PLANESWALKER, LONG_NAME, DOUBLE_FACED, WALL_OF_TEXT, REMINDER_TEXT, BARE_LAND]


def test_render_returns_a_one_bit_image_at_label_size():
    img = render(VANILLA)
    assert img.size == (LABEL_WIDTH_DOTS, LABEL_HEIGHT_DOTS) == (609, 406)
    assert img.mode == "1"


def test_render_honours_custom_dimensions():
    img = render(PLANESWALKER, width=300, height=200)
    assert img.size == (300, 200)


def test_render_output_packs_for_the_printer():
    width_bytes, height, data = raster.pack_image(render(VANILLA))
    assert (width_bytes, height) == ((609 + 7) // 8, 406)
    assert len(data) == width_bytes * height


def test_render_is_deterministic():
    assert render(PLANESWALKER).tobytes() == render(PLANESWALKER).tobytes()


@pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.name.split("\n")[0])
def test_render_draws_ink(card):
    assert _ink_bbox(render(card)) is not None


@pytest.mark.parametrize("card", ALL_CARDS, ids=lambda c: c.name.split("\n")[0])
def test_ink_stays_inside_the_canvas(card):
    """Ink must respect the margin, not merely land inside the image.

    getbbox() reports a box of pixels within the image by construction, so
    comparing it against the image bounds can never fail no matter what
    render() does. The margin is the real contract, and it is what a thermal
    head's edge tolerance actually needs.
    """
    img = render(card)
    left, top, right, bottom = _ink_bbox(img)
    margin = card_label._MARGIN
    assert left >= margin - 1 and top >= margin - 1
    assert right <= img.width - margin + 1
    assert bottom <= img.height - margin + 1


def test_vanilla_creature_renders_with_its_power_toughness():
    # No oracle text at all is the common case for old commons, and must not
    # blow up or produce a blank label.
    img = render(VANILLA)
    assert _ink_bbox(img) is not None
    assert card_label._stats(VANILLA) == "2/2"


def test_card_with_neither_text_nor_stats_leaves_no_dangling_rule():
    # Nothing should be drawn below the header block - no rule floating over an
    # empty label. The header cannot plausibly reach halfway down at any font.
    img = render(BARE_LAND)
    assert _ink_bbox(img)[3] < img.height // 2


def test_wall_of_text_is_truncated_rather_than_overrunning():
    # Against the bottom margin, not the image edge: bbox is inside the image
    # by construction, so the edge comparison could never have failed.
    img = render(WALL_OF_TEXT)
    assert _ink_bbox(img)[3] <= img.height - card_label._MARGIN + 1


# --- font resolution -------------------------------------------------------


def test_font_falls_back_when_no_candidate_path_exists():
    assert card_label._font(("/no/such/font.ttf",), 20) is not None


def test_font_resolves_a_candidate_path_when_one_exists():
    assert card_label._font(card_label._REGULAR_FONT_PATHS, 20) is not None


# --- truncation ------------------------------------------------------------


def test_truncate_leaves_text_that_already_fits():
    font = card_label._font(card_label._REGULAR_FONT_PATHS, 16)
    assert card_label._truncate(font, "Bear", 500) == "Bear"


def test_truncate_shortens_with_an_ellipsis_and_fits():
    font = card_label._font(card_label._REGULAR_FONT_PATHS, 16)
    result = card_label._truncate(font, "Ultimate Nightmare of Wizards of the Coast", 120)
    assert result.endswith(card_label._ELLIPSIS)
    assert result != "Ultimate Nightmare of Wizards of the Coast"
    assert card_label._text_width(font, result) <= 120


# --- wrapping --------------------------------------------------------------


UNLIMITED = 200  # a line cap high enough not to bind in wrapping tests


def test_wrap_treats_existing_newlines_as_hard_breaks():
    font = card_label._font(card_label._REGULAR_FONT_PATHS, 16)
    assert card_label._wrap(font, "Flying\nVigilance", 500, UNLIMITED) == ["Flying", "Vigilance"]


def test_wrap_keeps_the_face_separator_on_its_own_line():
    font = card_label._font(card_label._REGULAR_FONT_PATHS, 16)
    lines = card_label._wrap(font, "Draw a card.\n//\nFlying", 500, UNLIMITED)
    assert lines == ["Draw a card.", "//", "Flying"]


def test_wrap_wraps_within_a_paragraph():
    font = card_label._font(card_label._REGULAR_FONT_PATHS, 16)
    lines = card_label._wrap(font, "one two three four five six seven eight", 60, UNLIMITED)
    assert len(lines) > 1
    assert " ".join(lines).split() == "one two three four five six seven eight".split()


def test_wrap_breaks_a_word_wider_than_the_column():
    font = card_label._font(card_label._REGULAR_FONT_PATHS, 16)
    lines = card_label._wrap(font, "A" * 200, 200, UNLIMITED)
    assert len(lines) > 1
    assert all(card_label._text_width(font, line) <= 200 for line in lines)


def test_wrap_lines_all_fit_the_column():
    font = card_label._font(card_label._REGULAR_FONT_PATHS, 16)
    lines = card_label._wrap(font, PLANESWALKER.oracle_text, 400, UNLIMITED)
    assert all(card_label._text_width(font, line) <= 400 for line in lines)


def test_wrap_drops_leading_and_trailing_blank_lines():
    font = card_label._font(card_label._REGULAR_FONT_PATHS, 16)
    assert card_label._wrap(font, "\n\nFlying\n\n", 500, UNLIMITED) == ["Flying"]


def test_wrap_stops_at_the_line_cap():
    font = card_label._font(card_label._REGULAR_FONT_PATHS, 16)
    assert len(card_label._wrap(font, "word " * 500, 200, 5)) == 5


# --- body ladder -----------------------------------------------------------


def test_layout_body_steps_down_the_ladder_for_longer_text():
    short_font, _ = card_label._layout_body("Flying", 500, 200)
    long_font, _ = card_label._layout_body("word " * 150, 500, 200)
    assert card_label._line_height(long_font) < card_label._line_height(short_font)


def test_layout_body_fits_the_box_it_is_given():
    font, lines = card_label._layout_body(PLANESWALKER.oracle_text, 560, 240)
    assert len(lines) * card_label._line_height(font) <= 240


def test_layout_body_truncates_when_the_smallest_size_still_overflows():
    font, lines = card_label._layout_body("word " * 400, 560, 240)
    assert len(lines) * card_label._line_height(font) <= 240
    assert lines[-1].endswith(card_label._ELLIPSIS)


def test_layout_body_returns_nothing_when_there_is_no_room():
    _font_used, lines = card_label._layout_body("Flying", 560, 4)
    assert lines == []


# --- face-joined fields ----------------------------------------------------


def test_flatten_joins_faces_onto_one_line():
    assert card_label._flatten("Delver of Secrets\n//\nInsectile Aberration") == (
        "Delver of Secrets // Insectile Aberration"
    )


def test_flatten_drops_a_face_with_no_value():
    # A transform back has no mana cost of its own; the separator must go too.
    assert card_label._flatten("{U}\n//\n") == "{U}"


def test_flatten_handles_none_and_empty():
    assert card_label._flatten(None) == ""
    assert card_label._flatten("") == ""


# --- stats -----------------------------------------------------------------


def test_stats_formats_power_and_toughness():
    assert card_label._stats(_card(power="3", toughness="4")) == "3/4"


def test_stats_keeps_zero_power():
    assert card_label._stats(_card(power="0", toughness="1")) == "0/1"


def test_stats_keeps_non_numeric_power():
    assert card_label._stats(_card(power="*", toughness="1+*")) == "*/1+*"


def test_stats_uses_loyalty_for_a_planeswalker():
    assert card_label._stats(_card(loyalty="7")) == "7"


def test_stats_pairs_power_and_toughness_per_face():
    assert card_label._stats(DOUBLE_FACED) == "1/1 // 3/2"


def test_stats_mixes_power_toughness_and_loyalty_across_faces():
    # Jace, Vryn's Prodigy: a 0/2 creature that transforms into a loyalty-5
    # planeswalker, so the value for each face lives in a different field.
    jace = _card(power="0\n//\n", toughness="2\n//\n", loyalty="\n//\n5")
    assert card_label._stats(jace) == "0/2 // 5"


def test_stats_is_empty_when_the_card_has_neither():
    assert card_label._stats(_card()) == ""


# --- ingest round trip ------------------------------------------------------
# These cross the seam between ingest.card_row() and _stats(). Every other test
# in this file hand-builds a Card, which is how _stats came to assume a wire
# format the ingest never emits: it expected empty face positions to be kept,
# while the ingest drops them, so loyalty vanished from every flip-walker.


def _round_trip(entry: dict):
    """A Scryfall bulk entry taken through the real ingest into a Card."""
    import sqlite3

    from mtgkiosk import cards as cards_module
    from mtgkiosk import ingest

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cards_module.create_schema(conn)
    row = ingest.card_row(entry)
    assert row is not None
    conn.execute(
        f"INSERT INTO cards ({', '.join(f.name for f in __import__('dataclasses').fields(Card))}) "
        f"VALUES ({', '.join(['?'] * len(row))})",
        row,
    )
    stored = conn.execute("SELECT * FROM cards").fetchone()
    return Card(**{key: stored[key] for key in stored.keys()})


FLIP_WALKER = {
    "oracle_id": "jace-vryn",
    "name": "Jace, Vryn's Prodigy // Jace, Telepath Unbound",
    "layout": "transform",
    "type_line": "Creature — Human Wizard // Legendary Planeswalker — Jace",
    "card_faces": [
        {"name": "Jace, Vryn's Prodigy", "power": "0", "toughness": "2", "oracle_text": "Tap: draw."},
        {"name": "Jace, Telepath Unbound", "loyalty": "5", "oracle_text": "+1: target creature."},
    ],
}


def test_stats_keeps_loyalty_on_a_card_ingested_as_creature_then_planeswalker():
    card = _round_trip(FLIP_WALKER)
    # The ingest drops the empty face positions, so power/toughness/loyalty
    # arrive with no separators at all - the exact shape _stats got wrong.
    assert (card.power, card.toughness, card.loyalty) == ("0", "2", "5")
    assert card_label._stats(card) == "0/2 // 5"


def test_stats_pairs_both_faces_of_an_ingested_double_faced_creature():
    entry = {
        "oracle_id": "delver",
        "name": "Delver of Secrets // Insectile Aberration",
        "layout": "transform",
        "type_line": "Creature — Human Wizard // Creature — Human Insect",
        "card_faces": [
            {"name": "Delver of Secrets", "power": "1", "toughness": "1"},
            {"name": "Insectile Aberration", "power": "3", "toughness": "2"},
        ],
    }
    assert card_label._stats(_round_trip(entry)) == "1/1 // 3/2"


def test_stats_of_an_ingested_plain_planeswalker_is_just_its_loyalty():
    entry = {
        "oracle_id": "jace-tms",
        "name": "Jace, the Mind Sculptor",
        "layout": "normal",
        "type_line": "Legendary Planeswalker — Jace",
        "loyalty": "3",
    }
    assert card_label._stats(_round_trip(entry)) == "3"


# --- artwork labels ---------------------------------------------------------


def _solid_art(width, height):
    """Mid-grey, which Floyd-Steinberg turns into ink across the whole area.

    Geometry tests measure the ink bounding box, so the stand-in must not have
    near-white regions - those leave no ink and would under-report the size of
    the printed card.
    """
    return Image.new("L", (width, height), 128)


def _fake_art(width=626, height=457):
    """A gradient stands in for artwork: it dithers, unlike a flat fill."""
    art = Image.new("L", (width, height))
    art.putdata([(x * 255) // max(1, width - 1) for _ in range(height) for x in range(width)])
    return art


def test_render_with_art_matches_the_label_size_and_mode():
    img = card_label.render_with_art(VANILLA, _fake_art())
    assert img.size == (card_label.LABEL_WIDTH_DOTS, card_label.LABEL_HEIGHT_DOTS)
    assert img.mode == "1"


def test_render_with_art_draws_ink_in_the_art_column():
    img = card_label.render_with_art(VANILLA, _fake_art())
    column = img.crop((0, 0, card_label.ART_COLUMN_DOTS, img.height))
    assert _ink_bbox(column) is not None


def test_render_with_art_keeps_the_text_at_full_size():
    """The point of cropping to art: the text must not shrink to fit beside it.

    A whole-card image scaled to this label would put rules text near 11 dots,
    under the 16-dot floor where 203 DPI output turns to smudge. Rendering the
    text ourselves into the remaining column keeps it legible.
    """
    divider = 2  # width of the rule drawn between the art column and the text
    with_art = card_label.render_with_art(PLANESWALKER, _fake_art())
    text_region = with_art.crop(
        (card_label.ART_COLUMN_DOTS + divider, 0, with_art.width, with_art.height)
    )
    assert _ink_bbox(text_region) is not None

    # Same text into the same width, so the two must agree pixel for pixel;
    # anything else means the art column changed how the text was laid out.
    alone = card_label.render(
        PLANESWALKER,
        width=with_art.width - card_label.ART_COLUMN_DOTS,
        height=with_art.height,
    )
    assert text_region.tobytes() == alone.crop(
        (divider, 0, alone.width, alone.height)
    ).tobytes()


def test_render_with_art_crops_rather_than_letterboxes_a_landscape_crop():
    # A wide art crop fitted whole into a portrait column would leave most of
    # the column blank; every row of the column should carry some art.
    img = card_label.render_with_art(VANILLA, _fake_art(1200, 300))
    column = img.crop((0, 0, card_label.ART_COLUMN_DOTS, img.height))
    assert _ink_bbox(column)[3] > img.height * 0.8


def test_render_with_art_accepts_a_tiny_art_image():
    img = card_label.render_with_art(VANILLA, _fake_art(4, 3))
    assert img.size == (card_label.LABEL_WIDTH_DOTS, card_label.LABEL_HEIGHT_DOTS)


# --- full card image --------------------------------------------------------


def test_render_full_card_matches_the_label_size_and_mode():
    img = card_label.render_full_card(_solid_art(488, 680))
    assert img.size == (card_label.LABEL_WIDTH_DOTS, card_label.LABEL_HEIGHT_DOTS)
    assert img.mode == "1"


def test_render_full_card_rotates_a_portrait_card_onto_landscape_stock():
    """A portrait card fitted upright uses 48% of a 3x2 label; rotated, 93%.

    The rule is "rotate when it makes the card bigger", so it is asserted by
    measuring the printed area rather than by checking for a rotate() call.
    """
    portrait = _solid_art(488, 680)
    img = card_label.render_full_card(portrait, width=609, height=406)
    ink = _ink_bbox(img)
    printed_width = ink[2] - ink[0]
    # Upright would be about 291 dots wide; rotated is about 566.
    assert printed_width > 500


def test_render_full_card_leaves_a_portrait_label_upright():
    # The same rule has to reverse itself on 2x3 stock, so swapping label
    # orientation needs no code change.
    portrait = _solid_art(488, 680)
    img = card_label.render_full_card(portrait, width=406, height=609)
    ink = _ink_bbox(img)
    assert (ink[3] - ink[1]) > (ink[2] - ink[0])


def test_render_full_card_preserves_aspect_ratio():
    # A stretched card is not a copy of the card.
    source = _solid_art(488, 680)
    img = card_label.render_full_card(source, width=609, height=406)
    ink = _ink_bbox(img)
    printed = (ink[2] - ink[0]) / (ink[3] - ink[1])
    rotated_aspect = 680 / 488
    assert abs(printed - rotated_aspect) < 0.05


def test_render_full_card_never_crops_the_card():
    source = _solid_art(488, 680)
    img = card_label.render_full_card(source, width=609, height=406)
    ink = _ink_bbox(img)
    assert ink[0] >= 0 and ink[1] >= 0
    assert ink[2] <= img.width and ink[3] <= img.height
    # Fitted, not filled: one axis must have room left over.
    assert (ink[2] - ink[0]) < img.width or (ink[3] - ink[1]) < img.height
