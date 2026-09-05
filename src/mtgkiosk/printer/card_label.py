"""Card -> 1-bit label image for ThermalPrinter.print_image().

The production stock is a 3in x 2in overlay label (609 x 406 dots at 203 DPI)
stuck on top of an existing bulk card, not a card-sized replica. So this
renders card *text* only: at 203 DPI monochrome, card art turns to mud while
rules text stays crisp (see the Slice 1 design spec).

Everything is laid out against measured font metrics rather than fixed dot
offsets, because the font actually resolved at runtime differs between the Pi
(DejaVu) and a development machine (whatever Windows face is present). Only
the Pi ever prints, so a different face is purely cosmetic - but it means the
layout has to survive a font it wasn't tuned against.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from ..cards import Card

LABEL_WIDTH_DOTS = 609  # 3in at 203 DPI
LABEL_HEIGHT_DOTS = 406  # 2in at 203 DPI

# raster.pack_image() hard-thresholds to bilevel anyway, so rendering straight
# into mode "1" costs nothing and gains something: ImageDraw disables font
# antialiasing on "1" images, and unantialiased glyphs threshold far more
# evenly than grey ones at 203 DPI.
_MODE = "1"
_WHITE = 1
_BLACK = 0

_MARGIN = 14
_RULE_THICKNESS = 2
_GAP_AFTER_NAME = 4
_GAP_BEFORE_RULE = 8
_GAP_AFTER_RULE = 10
_GAP_BEFORE_STATS = 6
_META_COLUMN_GAP = 14

# Font size ladders in dots, largest first. Each block steps down until it fits,
# so a terse card gets big readable type and a wordy one degrades gracefully.
#
# The body ladder bottoms out at 16 dots, which is only about 5.7pt at 203 DPI.
# Going smaller would make more cards "fit", but a 203 DPI thermal head cannot
# resolve type that fine - it prints as a grey smudge. Truncating the tail of a
# wall-of-text card is the better failure: the rest of the label stays readable.
_NAME_SIZES = (40, 36, 32, 29, 26)
_META_SIZES = (22, 20, 18)
_BODY_SIZES = (22, 21, 20, 19, 18, 17, 16)
_STATS_SIZE = 30

_ELLIPSIS = "\u2026"
_FACE_SEPARATOR = "//"

# Tried in order; the Pi's DejaVu first, then the Windows faces a dev machine
# is likely to have, then Pillow's own built-in face as a guaranteed floor.
_REGULAR_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
)
_BOLD_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
)

# The fallback path can hand back either class, and they share no base type.
_Font = ImageFont.FreeTypeFont | ImageFont.ImageFont


@lru_cache(maxsize=64)
def _font(paths: tuple[str, ...], size: int) -> _Font:
    """First loadable font from `paths` at `size`, else Pillow's built-in face.

    Cached because a full label walks several ladder steps and would otherwise
    re-open and re-hint the same TTF a dozen times per print.
    """
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Pillow < 10.1 has no scalable built-in; one fixed bitmap size is all
        # the ladder gets, which is ugly but still renders.
        return ImageFont.load_default()


def _text_width(font: _Font, text: str) -> int:
    """Ink width of `text`, not its advance width.

    Fitting against ink is what keeps a glyph from being clipped mid-stroke at
    the label edge, which is the one failure the printer makes obvious.
    """
    if not text:
        return 0
    return int(math.ceil(font.getbbox(text)[2]))


def _line_height(font: _Font) -> int:
    """Baseline-to-baseline height of one line in this font, in dots."""
    try:
        ascent, descent = font.getmetrics()
        return ascent + descent
    except AttributeError:
        # Pillow's bitmap fallback font has no getmetrics(); a string carrying
        # both an ascender and a descender measures the same span.
        return font.getbbox("Ag")[3]


def _faces(value: str | None) -> list[str]:
    """Split a face-joined field into one entry per face, empties included.

    cards.py joins each face's fields with "\\n//\\n". Positions are kept even
    when a face's value is empty, because stats have to be paired back up
    across three separate fields (power, toughness, loyalty) by face index.
    """
    if not value:
        return []
    return [part.strip() for part in value.split(f"\n{_FACE_SEPARATOR}\n")]


def _flatten(value: str | None) -> str:
    """Collapse a face-joined field onto one line.

    Name, type line and mana cost each occupy a single row, so the separator
    becomes an inline " // ". Faces with an empty value (a transform back has
    no mana cost) are dropped, so no dangling separator is left behind.
    """
    return " // ".join(part for part in _faces(value) if part)


def _longest_prefix(font: _Font, text: str, max_width: int) -> int:
    """Length of the longest prefix of `text` whose ink fits `max_width`.

    Binary search rather than a walk back from the end: measuring is the
    expensive part here, and a scan costs one measurement per character of a
    string that may be the entire rules text of a card.
    """
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if _text_width(font, text[:mid]) <= max_width:
            low = mid
        else:
            high = mid - 1
    return low


def _truncate(font: _Font, text: str, max_width: int) -> str:
    """`text` shortened with an ellipsis until its ink fits `max_width`."""
    if _text_width(font, text) <= max_width:
        return text
    low, high = 0, len(text) - 1
    while low < high:
        mid = (low + high + 1) // 2
        if _text_width(font, text[:mid].rstrip() + _ELLIPSIS) <= max_width:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + _ELLIPSIS if low else ""


def _wrap_paragraph(font: _Font, text: str, max_width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        if len(lines) >= max_lines:
            return lines
        candidate = f"{current} {word}" if current else word
        if _text_width(font, candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        # A single word wider than the column has to break mid-word; letting it
        # through would overrun the label edge instead of merely looking bad.
        while _text_width(font, word) > max_width and len(lines) < max_lines:
            cut = max(1, _longest_prefix(font, word, max_width))
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _wrap(font: _Font, oracle_text: str, max_width: int, max_lines: int) -> list[str]:
    """Wrap oracle text, honouring the newlines already in it as hard breaks.

    Oracle text arrives pre-broken into abilities, and double-faced cards carry
    a bare "//" line between faces. Both are meaningful, so wrapping happens
    within each line rather than across the whole blob - which also keeps the
    face separator on a row of its own instead of trailing the end of an
    ability.

    Stops at `max_lines`. Nothing past the bottom of the text box is ever
    drawn, and without a cap a pathological blob of text would be wrapped in
    full once per rung of the font ladder.
    """
    paragraphs = [paragraph.strip() for paragraph in oracle_text.split("\n")]
    while paragraphs and not paragraphs[0]:
        paragraphs.pop(0)
    while paragraphs and not paragraphs[-1]:
        paragraphs.pop()

    lines: list[str] = []
    for paragraph in paragraphs:
        if len(lines) >= max_lines:
            break
        if paragraph:
            lines.extend(_wrap_paragraph(font, paragraph, max_width, max_lines - len(lines)))
        else:
            lines.append("")
    return lines


def _layout_body(oracle_text: str, max_width: int, max_height: int) -> tuple[_Font, list[str]]:
    """Pick the largest ladder size whose wrapped text fits, else truncate.

    Returns the chosen font and the lines to draw. An empty list means there is
    no room at all, which is preferable to drawing a line that runs off the
    bottom edge.
    """
    font = _font(_REGULAR_FONT_PATHS, _BODY_SIZES[-1])
    lines: list[str] = []
    fits = 0
    for size in _BODY_SIZES:
        font = _font(_REGULAR_FONT_PATHS, size)
        fits = max_height // _line_height(font)
        # One line past the box is enough to know it overflowed.
        lines = _wrap(font, oracle_text, max_width, fits + 1)
        if len(lines) <= fits:
            return font, lines

    # Smallest size still overflows: keep whole lines only, and mark the cut
    # with an ellipsis so a truncated card is never mistaken for a complete one.
    if fits < 1:
        return font, []
    lines = lines[:fits]
    lines[-1] = _truncate(font, lines[-1] + _ELLIPSIS, max_width)
    return font, lines


def _stats(card: Card) -> str:
    """Bottom-right corner text: power/toughness pairs, then any loyalty.

    Jace, Vryn's Prodigy is a 0/2 that transforms into a loyalty-5
    planeswalker and has to print "0/2 // 5".

    These fields cannot be paired by face index, because ingest.py drops a
    face that has no value for a field rather than leaving a hole: Jace
    arrives as power="0", toughness="2", loyalty="5", three single-entry
    lists carrying no record of which face each came from. An earlier version
    of this function assumed the holes were preserved and silently printed
    "0/2", dropping the loyalty on all 13 such cards in the export.

    So pairs are emitted in order and loyalties appended after them. That is
    correct for every real card: all 13 are creature-front, planeswalker-back,
    and none has a loyalty face ahead of a creature face.
    """
    powers = _faces(card.power)
    toughnesses = _faces(card.toughness)
    parts = []
    for index in range(max(len(powers), len(toughnesses))):
        power = powers[index] if index < len(powers) else ""
        toughness = toughnesses[index] if index < len(toughnesses) else ""
        if power and toughness:
            parts.append(f"{power}/{toughness}")
    parts.extend(loyalty for loyalty in _faces(card.loyalty) if loyalty)
    return " // ".join(parts)


ART_COLUMN_DOTS = 240


def render_with_art(
    card: Card,
    art: Image.Image,
    width: int = LABEL_WIDTH_DOTS,
    height: int = LABEL_HEIGHT_DOTS,
) -> Image.Image:
    """The text label with the card's artwork down the left-hand side.

    Takes Scryfall's art_crop - the artwork alone, no frame or text - rather
    than the whole card. Printing a whole card scaled to a 2in label would put
    its rules text at roughly 11 dots, below the 16-dot floor this module
    already established as the point where 203 DPI thermal output turns to
    grey smudge. Cropping to the art and re-rendering the text ourselves keeps
    the text at full size and gives the artwork a column wide enough to survive
    Floyd-Steinberg dithering.

    The art is cropped to fill its column rather than letterboxed: the crop is
    landscape and the column is portrait, so fitting it whole would waste most
    of the label on white space.
    """
    img = Image.new(_MODE, (width, height), color=_WHITE)

    column = min(ART_COLUMN_DOTS, width // 2)
    grey = art.convert("L")
    scale = max(column / grey.width, height / grey.height)
    scaled = grey.resize(
        (max(1, round(grey.width * scale)), max(1, round(grey.height * scale))),
        Image.LANCZOS,
    )
    left = (scaled.width - column) // 2
    top = (scaled.height - height) // 2
    panel = scaled.crop((left, top, left + column, top + height))
    # Dithered, not thresholded: a hard threshold turns artwork into blobs,
    # while error diffusion holds tone at the printer's one bit per dot.
    img.paste(panel.convert(_MODE, dither=Image.FLOYDSTEINBERG), (0, 0))

    text = render(card, width=width - column, height=height)
    img.paste(text, (column, 0))
    ImageDraw.Draw(img).line([(column, 0), (column, height)], fill=_BLACK, width=2)
    return img


def render(
    card: Card,
    width: int = LABEL_WIDTH_DOTS,
    height: int = LABEL_HEIGHT_DOTS,
) -> Image.Image:
    """Render `card` to a 1-bit image sized for the thermal label stock."""
    img = Image.new(_MODE, (width, height), color=_WHITE)
    draw = ImageDraw.Draw(img)

    left = _MARGIN
    right = width - _MARGIN
    column = right - left
    y = _MARGIN

    name = _flatten(card.name)
    name_font = _font(_BOLD_FONT_PATHS, _NAME_SIZES[-1])
    for size in _NAME_SIZES:
        name_font = _font(_BOLD_FONT_PATHS, size)
        if _text_width(name_font, name) <= column:
            break
    draw.text((left, y), _truncate(name_font, name, column), font=name_font, fill=_BLACK)
    y += _line_height(name_font) + _GAP_AFTER_NAME

    # Mana cost right-aligned, type line left-aligned into whatever is left, so
    # a long type line is truncated rather than colliding with the cost. Symbols
    # keep their braces: "{W/U}" is unambiguous where a bare "W/U" is not.
    type_line = _flatten(card.type_line)
    mana_cost = _flatten(card.mana_cost)
    meta_font = _font(_REGULAR_FONT_PATHS, _META_SIZES[-1])
    for size in _META_SIZES:
        meta_font = _font(_REGULAR_FONT_PATHS, size)
        combined = _text_width(meta_font, type_line) + _text_width(meta_font, mana_cost)
        if combined + _META_COLUMN_GAP <= column:
            break
    mana_width = _text_width(meta_font, mana_cost)
    if mana_cost:
        draw.text((right - mana_width, y), mana_cost, font=meta_font, fill=_BLACK)
        type_column = column - mana_width - _META_COLUMN_GAP
    else:
        type_column = column
    if type_line:
        draw.text(
            (left, y), _truncate(meta_font, type_line, type_column), font=meta_font, fill=_BLACK
        )
    rule_y = y + _line_height(meta_font) + _GAP_BEFORE_RULE
    y = rule_y + _RULE_THICKNESS + _GAP_AFTER_RULE

    stats = _stats(card)
    stats_font = _font(_BOLD_FONT_PATHS, _STATS_SIZE)
    stats_y = height - _MARGIN - _line_height(stats_font)
    # The stats badge reserves a full-width band rather than just its own
    # corner. That costs the body one line on a wordy planeswalker, but it makes
    # overlap structurally impossible instead of a wrapping edge case.
    body_bottom = (stats_y - _GAP_BEFORE_STATS) if stats else height - _MARGIN

    oracle_text = card.oracle_text or ""
    body_font, lines = (
        _layout_body(oracle_text, column, body_bottom - y)
        if oracle_text.strip() and body_bottom > y
        else (meta_font, [])
    )

    # A rule with nothing beneath it is the gap a vanilla land would otherwise
    # leave, so it is drawn only once there is something for it to separate.
    if lines or stats:
        draw.rectangle((left, rule_y, right - 1, rule_y + _RULE_THICKNESS - 1), fill=_BLACK)
    if stats:
        draw.text(
            (right - _text_width(stats_font, stats), stats_y),
            stats,
            font=stats_font,
            fill=_BLACK,
        )

    line_height = _line_height(body_font)
    for line in lines:
        if line == _FACE_SEPARATOR:
            # A short centred hairline reads as "the other face starts here".
            # A literal "//" alone on a row reads as a typo.
            inset = column // 3
            mid = y + line_height // 2
            draw.rectangle((left + inset, mid, right - 1 - inset, mid), fill=_BLACK)
        elif line:
            draw.text((left, y), line, font=body_font, fill=_BLACK)
        y += line_height

    return img
