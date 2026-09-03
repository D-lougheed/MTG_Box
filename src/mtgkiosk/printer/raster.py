"""Pillow image -> 1-bit packed rows for TSPL BITMAP. Pure function, no I/O.

Contract: a packed bit of 1 means "print this dot" (dark). Row length is
padded up to a whole byte, matching TSPL2's BITMAP row format.
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
        row = bytearray(width_bytes)
        for x in range(width):
            if pixels[x, y] == 0:  # PIL "1" mode: 0 = black
                row[x // 8] |= 0x80 >> (x % 8)
        rows.extend(row)

    return width_bytes, height, bytes(rows)
