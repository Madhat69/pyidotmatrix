"""Scrolling-text command builder. Renders characters to 1-bit bitmaps and wraps
them in the device's text packet. Needs Pillow and a font path (caller-provided).

Ported verbatim from the research lab; byte layout from 8none1's work.
"""

import zlib

from PIL import Image, ImageDraw, ImageFont

# Display modes (how the text appears/animates).
MODE_REPLACE = 0
MODE_MARQUEE = 1
MODE_REVERSED_MARQUEE = 2
MODE_VERTICAL_RISING = 3
MODE_VERTICAL_LOWERING = 4
MODE_BLINKING = 5
MODE_FADING = 6
MODE_TETRIS = 7
MODE_FILLING = 8

# Color modes (byte 6 of the metadata).
COLOR_WHITE = 0
COLOR_RGB = 1
COLOR_RAINBOW_1 = 2
COLOR_RAINBOW_2 = 3
COLOR_RAINBOW_3 = 4
COLOR_RAINBOW_4 = 5

# Each character is rendered into a fixed 16x32 1-bit bitmap.
_CHAR_WIDTH = 16
_CHAR_HEIGHT = 32
_CHAR_SEPARATOR = b"\x05\xff\xff\xff"


def build_text_packet(
    text: str,
    font_path: str,
    font_size: int = 16,
    text_mode: int = MODE_MARQUEE,
    speed: int = 95,
    color_mode: int = COLOR_WHITE,
    color: tuple[int, int, int] = (255, 255, 255),
    bg_color: tuple[int, int, int] | None = None,
) -> bytearray:
    """Builds the full text command. bg_color None means a black background."""
    bitmaps = _text_to_bitmaps(text, font_path, font_size)
    bg_mode = 0 if bg_color is None else 1
    resolved_bg = bg_color if bg_color is not None else (0, 0, 0)

    metadata = bytearray(
        [0, 0, 0, 1, text_mode, speed, color_mode, *color, bg_mode, *resolved_bg]
    )
    metadata[0:2] = bitmaps.count(_CHAR_SEPARATOR).to_bytes(2, "little")  # character count
    packet = metadata + bitmaps

    header = bytearray([0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 12])
    header[0:2] = (len(packet) + len(header)).to_bytes(2, "little")
    header[5:9] = len(packet).to_bytes(4, "little")
    header[9:13] = zlib.crc32(packet).to_bytes(4, "little")
    return header + packet


def _text_to_bitmaps(text: str, font_path: str, font_size: int) -> bytearray:
    """Renders each character to a separator-prefixed 1-bit bitmap."""
    font = ImageFont.truetype(font_path, font_size)
    stream = bytearray()
    for char in text:
        image = Image.new("1", (_CHAR_WIDTH, _CHAR_HEIGHT), 0)
        draw = ImageDraw.Draw(image)
        _, _, text_width, text_height = draw.textbbox((0, 0), char, font=font)
        draw.text(
            ((_CHAR_WIDTH - text_width) // 2, (_CHAR_HEIGHT - text_height) // 2),
            char,
            fill=1,
            font=font,
        )
        stream.extend(_CHAR_SEPARATOR + _pack_bitmap(image))
    return stream


def _pack_bitmap(image: Image.Image) -> bytearray:
    """Packs a 1-bit image into bytes, 8 pixels per byte, row by row."""
    bitmap = bytearray()
    byte = 0
    for y in range(_CHAR_HEIGHT):
        for x in range(_CHAR_WIDTH):
            if x % 8 == 0:
                byte = 0
            byte |= (image.getpixel((x, y)) & 1) << (x % 8)
            if x % 8 == 7 or x == _CHAR_WIDTH - 1:
                bitmap.append(byte)
    return bitmap
