"""Pillow image -> 1-bit packed rows for TSPL BITMAP. Pure function, no I/O.

Contract: **a packed bit of 0 means "print this dot" (dark), 1 means leave the
paper alone.** That is TSPL2's BITMAP convention, and it is the inverse of the
intuitive one - which is exactly how it was got wrong. The original version of
this module packed 1 for ink, so every label printed as a solid black rectangle
with the text knocked out in white. It survived until the first real card was
printed because nothing else exercises the BITMAP path: the printer self-test
uses the printer's own SELFTEST command, and text labels use TSPL TEXT.

Rows are padded up to a whole byte, and the padding bits are **1**. At 609 dots
a row pads to 616, so seven columns of padding printing black would put a stripe
down the right-hand edge of every label. Building each row from 0xFF and
clearing bits for ink gets both the polarity and the padding right at once.
"""

from PIL import Image


def pack_image(img: Image.Image, dither: bool = False) -> tuple[int, int, bytes]:
    gray = img.convert("L")
    if dither:
        bw = gray.convert("1")
    else:
        bw = gray.point(lambda p: 255 if p >= 128 else 0).convert("1")

    width, height = bw.size
    width_bytes = (width + 7) // 8
    pixels = bw.load()

    rows = bytearray()
    for y in range(height):
        row = bytearray(b"\xff" * width_bytes)
        for x in range(width):
            if pixels[x, y] == 0:  # PIL "1" mode: 0 = black, and black is ink
                row[x // 8] &= ~(0x80 >> (x % 8)) & 0xFF
        rows.extend(row)

    return width_bytes, height, bytes(rows)
