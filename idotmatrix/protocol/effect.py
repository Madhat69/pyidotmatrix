"""Effect-mode command builder. Pure function.

The device animates one of seven built-in effects using 2..7 colors.
"""

from idotmatrix.validation import validate_rgb

MIN_COLORS = 2
MAX_COLORS = 7


def build_show(style: int, colors: list[tuple[int, int, int]]) -> bytearray:
    if style not in range(7):
        raise ValueError(f"effect style must be 0..6, got {style}")
    if not (MIN_COLORS <= len(colors) <= MAX_COLORS):
        raise ValueError(f"effect needs {MIN_COLORS}..{MAX_COLORS} colors, got {len(colors)}")
    for color in colors:
        validate_rgb(color)

    # The two length fields count colors, not color components.
    components = [channel for color in colors for channel in color]
    return bytearray(
        [
            6 + len(colors),
            0, 3, 2,
            style % 256,
            90,
            len(colors) % 256,
        ]
        + components
    )
