"""Graffiti-mode packet builder: set one or more pixels to a single color.

Graffiti writes draw over the current framebuffer without clearing it, which
makes them the cheap path for small per-frame changes (deltas). Pure function.
"""

from idotmatrix.validation import validate_rgb

# Device accepts at most this many coordinates in one command (found by testing).
MAX_PIXELS_PER_COMMAND = 255

# Mirror modes 1-4. Mode 1 is plain (no mirroring); 2-4 mirror the drawn pixels
# into other quadrants. The exact visual per mode is unverified — see ROADMAP.
MIRROR_NONE = 1
MIN_MIRROR = 1
MAX_MIRROR = 4

_HEADER_SIZE = 8


def build_set_pixels(
    color: tuple[int, int, int],
    xys: list[tuple[int, int]],
    mirror: int = MIRROR_NONE,
) -> bytearray:
    """Builds a command setting every coordinate in xys to color.

    Raises ValueError if more than MAX_PIXELS_PER_COMMAND coordinates are given
    (the caller batches), or if mirror is outside 1..4.
    """
    if len(xys) > MAX_PIXELS_PER_COMMAND:
        raise ValueError(f"xys must have length <= {MAX_PIXELS_PER_COMMAND}, got {len(xys)}")
    if not (MIN_MIRROR <= mirror <= MAX_MIRROR):
        raise ValueError(f"mirror must be {MIN_MIRROR}..{MAX_MIRROR}, got {mirror}")
    validate_rgb(color)

    red, green, blue = color
    size = _HEADER_SIZE + 2 * len(xys)
    payload = bytearray(
        [
            size % 256,   # length LSB
            size // 256,  # length MSB (0 or 1)
            5,            # graffiti mode
            mirror,       # mirroring mode 1-4
            0,            # unknown, always 0
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
