"""TSPL2 command builder. Pure functions: arguments in, bytes out. No I/O.

Every dimension is written with an explicit unit suffix. Do not add a
unitless code path — this printer's ambient default unit is millimeters,
and a unitless `SIZE 4,6` meant as inches silently produced a 4mm x 6mm
print area during hardware bring-up (see the Slice 1 design spec).
"""


def size_mm(width_mm: float, height_mm: float) -> bytes:
    return f"SIZE {width_mm} mm,{height_mm} mm\r\n".encode("ascii")


def gap_mm(gap_mm_value: float, offset_mm: float = 0) -> bytes:
    return f"GAP {gap_mm_value} mm,{offset_mm} mm\r\n".encode("ascii")


def direction(value: int) -> bytes:
    return f"DIRECTION {value}\r\n".encode("ascii")


def cls() -> bytes:
    return b"CLS\r\n"


def text(x: int, y: int, font: str, rotation: int, x_mult: int, y_mult: int, content: str) -> bytes:
    escaped = content.replace('"', '\\"')
    return f'TEXT {x},{y},"{font}",{rotation},{x_mult},{y_mult},"{escaped}"\r\n'.encode("ascii")


def bitmap(x: int, y: int, width_bytes: int, height: int, mode: int, data: bytes) -> bytes:
    header = f"BITMAP {x},{y},{width_bytes},{height},{mode},".encode("ascii")
    return header + data + b"\r\n"


def print_label(sets: int = 1, copies: int = 1) -> bytes:
    return f"PRINT {sets},{copies}\r\n".encode("ascii")


def selftest() -> bytes:
    return b"SELFTEST\r\n"
