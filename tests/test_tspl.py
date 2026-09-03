from mtgkiosk.printer import tspl


def test_size_mm_formats_explicit_units():
    assert tspl.size_mm(76.2, 50.8) == b"SIZE 76.2 mm,50.8 mm\r\n"


def test_gap_mm_formats_explicit_units():
    assert tspl.gap_mm(3, 0) == b"GAP 3 mm,0 mm\r\n"


def test_gap_mm_defaults_offset_to_zero():
    assert tspl.gap_mm(3) == b"GAP 3 mm,0 mm\r\n"


def test_direction():
    assert tspl.direction(1) == b"DIRECTION 1\r\n"


def test_cls():
    assert tspl.cls() == b"CLS\r\n"


def test_text_basic():
    result = tspl.text(100, 100, "3", 0, 1, 1, "TSPL OK")
    assert result == b'TEXT 100,100,"3",0,1,1,"TSPL OK"\r\n'


def test_text_escapes_embedded_quotes():
    result = tspl.text(0, 0, "3", 0, 1, 1, 'Say "hi"')
    assert result == b'TEXT 0,0,"3",0,1,1,"Say \\"hi\\""\r\n'


def test_bitmap_embeds_raw_bytes_with_header():
    data = bytes([0xFF, 0x00, 0xFF])
    result = tspl.bitmap(10, 20, 1, 3, 0, data)
    assert result == b"BITMAP 10,20,1,3,0," + data + b"\r\n"


def test_print_label_default():
    assert tspl.print_label() == b"PRINT 1,1\r\n"


def test_print_label_explicit_counts():
    assert tspl.print_label(sets=2, copies=3) == b"PRINT 2,3\r\n"


def test_selftest():
    assert tspl.selftest() == b"SELFTEST\r\n"


def test_text_escapes_trailing_backslash_before_closing_quote():
    result = tspl.text(0, 0, "3", 0, 1, 1, "trailing backslash\\")
    assert result == b'TEXT 0,0,"3",0,1,1,"trailing backslash\\\\"\r\n'


def test_text_escapes_backslash_before_quote_when_adjacent():
    result = tspl.text(0, 0, "3", 0, 1, 1, 'back\\slash and "quote"')
    assert result == b'TEXT 0,0,"3",0,1,1,"back\\\\slash and \\"quote\\""\r\n'
