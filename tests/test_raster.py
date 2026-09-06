from PIL import Image

from mtgkiosk.printer import raster

# TSPL BITMAP prints a dot where the bit is 0. These assertions were all
# inverted until a real card was printed and came out as a black rectangle with
# the text knocked out in white.


def test_pack_image_all_white_leaves_every_bit_set():
    img = Image.new("L", (8, 2), color=255)
    width_bytes, height, data = raster.pack_image(img)
    assert (width_bytes, height) == (1, 2)
    assert data == bytes([0xFF, 0xFF])


def test_pack_image_all_black_clears_every_bit():
    img = Image.new("L", (8, 2), color=0)
    width_bytes, height, data = raster.pack_image(img)
    assert (width_bytes, height) == (1, 2)
    assert data == bytes([0x00, 0x00])


def test_pack_image_left_half_black_right_half_white():
    img = Image.new("L", (8, 1), color=255)
    for x in range(4):
        img.putpixel((x, 0), 0)
    _, _, data = raster.pack_image(img)
    assert data == bytes([0b00001111])


def test_pack_image_pads_width_to_byte_boundary():
    img = Image.new("L", (5, 1), color=0)
    width_bytes, _, data = raster.pack_image(img)
    assert width_bytes == 1
    assert data == bytes([0b00000111])


def test_padding_bits_are_white_not_ink():
    """Padding must not print, or every label gets a stripe down its edge.

    A 609-dot label pads to 616 bits, so seven columns of padding printing
    black would be a visible black bar on the right of every print.
    """
    img = Image.new("L", (609, 1), color=255)
    width_bytes, _, data = raster.pack_image(img)
    assert width_bytes == 77
    # The final byte carries one real column plus seven of padding; all white.
    assert data[-1] == 0xFF

    black = Image.new("L", (609, 1), color=0)
    _, _, black_data = raster.pack_image(black)
    # Real columns are ink, padding is still blank: 0b0_1111111.
    assert black_data[-1] == 0b01111111


def test_pack_image_without_dither_uses_hard_threshold():
    img = Image.new("L", (8, 1), color=127)
    _, _, data = raster.pack_image(img, dither=False)
    assert data == bytes([0x00])


def test_pack_image_with_dither_differs_from_hard_threshold():
    img = Image.new("L", (8, 1), color=127)
    _, _, dithered = raster.pack_image(img, dither=True)
    _, _, hard = raster.pack_image(img, dither=False)
    assert dithered != hard


def test_a_rendered_label_is_mostly_blank_paper():
    """End to end sanity: a text label must not be a mostly-black rectangle.

    This is the property the polarity bug violated, stated in terms a person
    can check against a physical print rather than as a bit pattern.
    """
    from mtgkiosk.cards import Card
    from mtgkiosk.printer import card_label

    card = Card(id="x", name="Grizzly Bears", type_line="Creature — Bear",
                mana_cost="{1}{G}", power="2", toughness="2")
    _, _, data = raster.pack_image(card_label.render(card))
    ink_bits = sum(8 - bin(byte).count("1") for byte in data)
    assert ink_bits < len(data) * 8 * 0.25
