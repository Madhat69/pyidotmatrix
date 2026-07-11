"""Clock-mode command builder. Pure function.

The device renders a clock face itself in one of eight styles.
"""

from idotmatrix.validation import validate_rgb

# Clock face styles.
STYLE_RGB_SWIPE_OUTLINE = 0
STYLE_CHRISTMAS_TREE = 1
STYLE_CHECKERS = 2
STYLE_COLOR = 3
STYLE_HOURGLASS = 4
STYLE_ALARM_CLOCK = 5
STYLE_OUTLINES = 6
STYLE_RGB_CORNERS = 7

_SHOW_DATE_FLAG = 128
_HOUR24_FLAG = 64


def build_show(
    style: int,
    show_date: bool = True,
    hour24: bool = True,
    color: tuple[int, int, int] = (255, 255, 255),
) -> bytearray:
    if style not in range(8):
        raise ValueError(f"clock style must be 0..7, got {style}")
    validate_rgb(color)
    flags = style
    if show_date:
        flags |= _SHOW_DATE_FLAG
    if hour24:
        flags |= _HOUR24_FLAG
    red, green, blue = color
    return bytearray([8, 0, 6, 1, flags, red, green, blue])
