"""Scrolling-text command builder. Renders characters to 1-bit bitmaps and wraps
them in the device's text packet. Needs Pillow and a font path (caller-provided).

Ported verbatim from the research lab; byte layout from 8none1's work.

Two builders live here:
  build_text_packet        the legacy/generic sender -- REJECTED by 32x32
                            firmware (probe 2026-07-19: device NACKs type=3
                            subtype=0 for all text modes). Matches the
                            decompiled app's sendTextTo832 wire layout.
  build_text_packet_32x32  ported from TextAgreement.sendTextTo3232 in the
                            decompiled APK (com.tech.pyidotmatrix.core.data).
                            See its docstring for the full derivation.

The APK has three more per-size senders this driver does not port:
sendTextTo1616, sendTextTo1664, sendTextTo6464 -- each targets a different
physical panel and, per the source, shares sendTextTo3232's byte layout
exactly except for byte 2 of the outer 16-byte-header's inner metadata
(see build_text_packet_32x32's docstring). Porting them is future work, not
scoped here.
"""

import binascii
from typing import cast

from PIL import Image, ImageDraw, ImageFont

from pyidotmatrix.protocol import bytes_

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
    """Builds the full text command. bg_color None means a black background.

    LEGACY/GENERIC -- REJECTED by 32x32 firmware (probe 2026-07-19: the device
    NACKs type=3 subtype=0 for all text modes). This builder matches the
    decompiled app's sendTextTo832 wire layout (metadata byte index 2 = 0,
    the "8-row LED family" flag). For a 32x32 panel use
    build_text_packet_32x32 instead, whose docstring documents exactly what
    differs. Kept as-is -- it may still be correct for other panel sizes this
    driver hasn't probed.
    """
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
    header[9:13] = (binascii.crc32(packet) & 0xFFFFFFFF).to_bytes(4, "little")
    return header + packet


def build_text_packet_32x32(
    text: str,
    font_path: str,
    font_size: int = 16,
    text_mode: int = MODE_MARQUEE,
    speed: int = 95,
    color_mode: int = COLOR_WHITE,
    color: tuple[int, int, int] = (255, 255, 255),
    bg_color: tuple[int, int, int] | None = None,
) -> list[list[bytearray]]:
    """Builds the text command for a 32x32 panel. bg_color None means black.

    Ported from TextAgreement.sendTextTo3232 in the decompiled APK
    (com.tech.pyidotmatrix.core.data.TextAgreement, ~line 1076). That method
    takes a fontSize parameter (16 or 32) that switches between two glyph-cell
    branches (getText16Width/height=16 vs getText32Width/height=32); this
    builder follows its else-branch (fontSize != 16): non-CJK characters get
    getText32Width() == 16px-wide glyphs at 32px tall (Text1664.isChinese/
    isJapaneseCharacter/isKoreanCharacter all return 32px wide instead -- not
    reproduced here, this driver has no CJK font-selection logic, same scope
    as build_text_packet). A 16x32 1-bit glyph packs to exactly 64 bytes
    (16*32/8), which is why the per-char tag is always byte 5 (data.length==64
    -> tag 5, else tag 6, TextAgreement.java ~line 1168) -- the same 0x05
    separator this driver already hardcodes for build_text_packet. That,
    combined with Text1664.getTextData's bit-packing (row-major, LSB-first,
    byte-aligned once width is a multiple of 8), means _text_to_bitmaps and
    _pack_bitmap below are ALREADY byte-identical to the vendor's 32x32-class
    glyph encoding -- reused unchanged.

    THE MONEY BYTE (root cause of the 32x32 NACK): sendTextTo3232's 14-byte
    metadata sets byte index 2 to 1 (TextAgreement.java line 1195,
    "bArr3[2] = 1"), the same value sendTextTo1616 uses -- a "row-class" flag
    meaning "16-or-32-row glyph family". build_text_packet (matching
    sendTextTo832) sets that same byte to 0 ("8-row family", line 228 of the
    decompile). Every other field -- char-count LE at metadata[0:2], mode/
    speed/color-mode/RGB/bg layout, the outer 16-byte chunk header (type=3,
    subtype=0, LE length/total-size/CRC32, trailing [0,0,12]), and the
    4096-byte chunk-then-BLE-split pipeline (getSendData4096/getSendData,
    TextAgreement.java ~line 2760/2729) -- is IDENTICAL between the two
    senders. So the generic builder's packet was never malformed; it was
    self-consistently describing itself as the wrong LED-row family, and the
    32x32 firmware NACKs on sight.

    Also ported: the pure-black-foreground guard present in every sendTextTo*
    variant (line ~1202-1205) -- color=(0,0,0) is rewritten on the wire to
    (0,0,1) (an invisible-text guard in the vendor app); any other color,
    including other blacks-with-nonzero-blue, passes through unchanged.

    Endianness (see module docstring's cross-reference to the Timer/Schedule
    finding): ByteUtils.short2Bytes returns [hi, lo] but every call site here
    writes byte[0]=lo, byte[1]=hi -- i.e. LE on the wire, matching
    build_text_packet. ByteUtils.int2byte already returns LE directly. Both
    confirmed by reading ByteUtils.java, not assumed from the Timer/Schedule
    precedent.

    SOURCE-CONFIRMED from the decompile; hardware verification pending (the
    Director will probe this on a real 32x32 panel immediately after this
    lands).
    """
    bitmaps = _text_to_bitmaps(text, font_path, font_size)
    bg_mode = 0 if bg_color is None else 1
    resolved_bg = bg_color if bg_color is not None else (0, 0, 0)

    fg = list(color)
    if fg[0] == 0 and fg[1] == 0 and fg[2] == 0:
        fg[2] = 1  # device quirk: pure-black foreground would be invisible text

    metadata = bytearray(
        [0, 0, 1, 1, text_mode, speed, color_mode, *fg, bg_mode, *resolved_bg]
    )
    metadata[0:2] = len(text).to_bytes(2, "little")  # character count
    packet = bytes(metadata + bitmaps)

    return bytes_.build_chunked_packets(packet, _build_header_32x32)


def _build_header_32x32(chunk: bytearray, payload: bytes, is_first: bool) -> bytes:
    """The 16-byte header prefixed to each 4K chunk (identical layout to the
    generic build_text_packet's single-chunk header, chunked here for
    payloads that exceed 4096 bytes -- see getSendData4096 in the decompile)."""
    header = bytearray(16)
    header[0:2] = bytes_.short_to_bytes_le(len(chunk) + 16)  # length incl. header
    header[2] = 3  # command/type
    header[3] = 0  # sub-command
    header[4] = 0 if is_first else 2  # first vs continuation
    header[5:9] = bytes_.int_to_bytes_le(len(payload))  # total packet size
    header[9:13] = bytes_.int_to_bytes_le(binascii.crc32(payload) & 0xFFFFFFFF)  # CRC32
    header[13:15] = b"\x00\x00"
    header[15] = 12
    return bytes(header)


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
            pixel = cast(int, image.getpixel((x, y)))  # mode "1" bitmap: always an int
            byte |= (pixel & 1) << (x % 8)
            if x % 8 == 7 or x == _CHAR_WIDTH - 1:
                bitmap.append(byte)
    return bitmap
