"""Graffiti-mode packet builder: set one or more pixels to a single color.

Graffiti writes draw over the current framebuffer without clearing it, which
makes them the cheap path for small per-frame changes (deltas). Pure function.

Header layout (HARDWARE-MAPPED 2026-07-21, probes/probe_graffiti_transform*.py
and probe_graffiti_byte3_*.py, single-pixel/block discriminators on a real
32x32):

    [len_lo, len_hi, 5, REQUIRED_1, move_type, r, g, b] + (x, y) pairs

Byte 3 is NOT a mirror field: value 1 -- the constant the vendor app hardcodes
(SendCore.getDataType(5) = {5, 1}) -- is the ONLY value that draws. 2 is
nacked [5,0,5,2,0]; 0, 3, and 4 are acked-and-silently-swallowed (nothing
renders). The 2026-07-12 sweep that reported "0/1/2/4 identical" re-sent the
same coordinates over an already-lit pattern, so the persisting pixels made
five no-ops look like four successes -- observer illusion, corrected.

Byte 4 is the real option field and matches the APK's DiyImageMoveType enum:
0 = plain draw; 1 = HORIZONTAL_MIRROR and 2 = VERTICAL_MIRROR (both draw the
given pixels PLUS a mirrored copy across the panel's center axis --
single-pixel-confirmed); 3 (enum: OVERALL_MOVEMENT) draws plainly for static
sends, no motion observed; 4 (enum: ERASE) drew plainly in the one test that
placed it center-screen -- semantics unresolved, treat 3 and 4 as unmapped.
"""

from pyidotmatrix.validation import validate_rgb

# Device accepts at most this many coordinates in one command (found by testing).
MAX_PIXELS_PER_COMMAND = 255

# DiyImageMoveType values for the byte-4 option field (see module docstring).
MOVE_NONE = 0
MOVE_HORIZONTAL_MIRROR = 1
MOVE_VERTICAL_MIRROR = 2
_MAPPED_MOVE_TYPES = (MOVE_NONE, MOVE_HORIZONTAL_MIRROR, MOVE_VERTICAL_MIRROR)

# Byte 3: the only value the device draws for; every alternative is a nack or
# a silent no-op (module docstring). Not caller-selectable.
_REQUIRED_BYTE3 = 1

_HEADER_SIZE = 8


def build_set_pixels(
    color: tuple[int, int, int],
    xys: list[tuple[int, int]],
    move_type: int = MOVE_NONE,
) -> bytearray:
    """Builds a command setting every coordinate in xys to color.

    move_type MOVE_HORIZONTAL_MIRROR / MOVE_VERTICAL_MIRROR additionally draws
    a mirrored copy of the pixels across the corresponding center axis.

    Raises ValueError if more than MAX_PIXELS_PER_COMMAND coordinates are given
    (the caller batches), or if move_type is not one of the mapped values.
    """
    if len(xys) > MAX_PIXELS_PER_COMMAND:
        raise ValueError(f"xys must have length <= {MAX_PIXELS_PER_COMMAND}, got {len(xys)}")
    if move_type not in _MAPPED_MOVE_TYPES:
        raise ValueError(f"move_type must be one of {_MAPPED_MOVE_TYPES} (DiyImageMoveType), got {move_type}")
    validate_rgb(color)

    red, green, blue = color
    size = _HEADER_SIZE + 2 * len(xys)
    payload = bytearray(
        [
            size % 256,   # length LSB
            size // 256,  # length MSB (0 or 1)
            5,            # graffiti mode
            _REQUIRED_BYTE3,
            move_type,
            red,
            green,
            blue,
        ]
        + [0] * (size - _HEADER_SIZE)
    )
    for i, (x, y) in enumerate(xys):
        payload[_HEADER_SIZE + 2 * i] = x
        payload[_HEADER_SIZE + 2 * i + 1] = y
    return payload
