from PIL import Image

from mtgkiosk.printer import raster


def test_pack_image_all_white_is_all_zero_bits():
    img = Image.new("L", (8, 2), color=255)
    width_bytes, height, data = raster.pack_image(img)
    assert (width_bytes, height) == (1, 2)
    assert data == bytes([0x00, 0x00])


def test_pack_image_all_black_is_all_one_bits():
    img = Image.new("L", (8, 2), color=0)
    width_bytes, height, data = raster.pack_image(img)
    assert (width_bytes, height) == (1, 2)
    assert data == bytes([0xFF, 0xFF])


def test_pack_image_left_half_black_right_half_white():
    img = Image.new("L", (8, 1), color=255)
    for x in range(4):
        img.putpixel((x, 0), 0)
    _, _, data = raster.pack_image(img)
    assert data == bytes([0b11110000])


def test_pack_image_pads_width_to_byte_boundary():
    img = Image.new("L", (5, 1), color=0)
    width_bytes, _, data = raster.pack_image(img)
    assert width_bytes == 1
    assert data == bytes([0b11111000])


def test_pack_image_without_dither_uses_hard_threshold():
    img = Image.new("L", (8, 1), color=127)
    _, _, data = raster.pack_image(img, dither=False)
    assert data == bytes([0xFF])
