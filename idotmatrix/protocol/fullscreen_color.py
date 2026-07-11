"""Fullscreen solid-color command builder. Pure function."""

from idotmatrix.validation import validate_rgb


def build_show_color(color: tuple[int, int, int]) -> bytearray:
    validate_rgb(color)
    red, green, blue = color
    return bytearray([7, 0, 2, 2, red, green, blue])
