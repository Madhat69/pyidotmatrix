"""Scrolling-text command builder. Renders characters to 1-bit bitmaps and wraps
them in the device's text packet. Needs Pillow and a font path (caller-provided).

Ported verbatim from the research lab; byte layout from 8none1's work.

Two builders live here:
  build_text_packet        the legacy/generic sender -- ACCEPTED and SAVED by
                            32x32 firmware but renders TRUNCATED ("HELLO" ->
                            "HEL", A/B 2026-07-20); the earlier 2026-07-19
                            "device NACKs it" reading was a StatusAck SAVED
                            misparse (protocol/response.py), not an actual
                            rejection. Matches the decompiled app's
                            sendTextTo832 wire layout.
  build_text_packet_32x32  ported from TextAgreement.sendTextTo3232 in the
                            decompiled APK (com.tech.pyidotmatrix.core.data).
                            Renders fully (not truncated) on 32x32 -- see its
                            docstring for the full derivation.

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

# Glyph cells, keyed by the vendor app's fontSize switch (sendTextTo3232 takes
# 16 or 32 and branches on it). 32 -> a 16x32 cell packing to 64 bytes; 16 -> an
# 8x16 cell packing to 16 bytes, the cell the app actually used in the
# 2026-07-25 HCI capture.
_GLYPH_CELLS = {32: (16, 32), 16: (8, 16)}

# Default cell (the driver's historical one, unchanged for build_text_packet).
_CHAR_WIDTH, _CHAR_HEIGHT = _GLYPH_CELLS[32]

# Per-glyph separator: a tag byte then ff ff ff. The tag depends on the packed
# glyph size. 64 bytes -> 5 is long-standing and matches the decompile; 16 bytes
# -> 2 is CAPTURE-CONFIRMED (2026-07-25 vendor-app HCI capture), which also
# falsified this driver's old "data.length == 64 -> tag 5, else tag 6" reading
# of TextAgreement.java: 16-byte glyphs carry tag 2, not 6. 6 is kept only as
# the fallback for cell sizes nobody has observed.
_SEPARATOR_TAGS = {64: 5, 16: 2}
_SEPARATOR_TAG_FALLBACK = 6
_CHAR_SEPARATOR = bytes([_SEPARATOR_TAGS[64], 0xFF, 0xFF, 0xFF])


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

    LEGACY/GENERIC -- ACCEPTED and SAVED by 32x32 firmware (StatusAck SAVED on
    type=3 subtype=0), but renders TRUNCATED there: "HELLO" comes out "HEL"
    (A/B 2026-07-20, see capabilities.py's text.show_generic_builder entry).
    The earlier 2026-07-19 "device NACKs it" reading was a StatusAck SAVED
    misparse (protocol/response.py), not an actual rejection. This builder
    matches the decompiled app's sendTextTo832 wire layout (metadata byte
    index 2 = 0, the "8-row LED family" flag). For a 32x32 panel use
    build_text_packet_32x32 instead, which renders fully -- whose docstring
    documents exactly what differs. Kept as-is -- it may still be correct for
    other panel sizes this driver hasn't probed.
    """
    bitmaps = _text_to_bitmaps(text, font_path, font_size)
    bg_mode = 0 if bg_color is None else 1
    resolved_bg = bg_color if bg_color is not None else (0, 0, 0)

    metadata = bytearray([0, 0, 0, 1, text_mode, speed, color_mode, *color, bg_mode, *resolved_bg])
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
    glyph_height: int = 32,
) -> list[list[bytearray]]:
    """Builds the text command for a 32x32 panel. bg_color None means black.

    glyph_height selects the vendor app's own glyph-cell branch (its fontSize
    switch, 16 or 32): 32 keeps this driver's historical 16x32 cell (64 bytes
    per glyph, separator tag 5); 16 uses the 8x16 cell (16 bytes per glyph,
    separator tag 2) that the app was captured using on 2026-07-25. Everything
    else about the packet -- header, metadata, bit order -- is identical.

    Ported from TextAgreement.sendTextTo3232 in the decompiled APK
    (com.tech.pyidotmatrix.core.data.TextAgreement, ~line 1076). That method
    takes a fontSize parameter (16 or 32) that switches between two glyph-cell
    branches (getText16Width/height=16 vs getText32Width/height=32); this
    builder follows its else-branch (fontSize != 16): non-CJK characters get
    getText32Width() == 16px-wide glyphs at 32px tall (Text1664.isChinese/
    isJapaneseCharacter/isKoreanCharacter all return 32px wide instead -- not
    reproduced here, this driver has no CJK font-selection logic, same scope
    as build_text_packet). A 16x32 1-bit glyph packs to exactly 64 bytes
    (16*32/8) and carries per-char tag 5 -- the same 0x05 separator this driver
    already hardcodes for build_text_packet. That, combined with
    Text1664.getTextData's bit-packing (row-major, LSB-first, byte-aligned once
    width is a multiple of 8), means _text_to_bitmaps and _pack_bitmap below
    are ALREADY byte-identical to the vendor's 32x32-class glyph encoding --
    reused unchanged.

    CORRECTION 2026-07-25 (vendor-app HCI capture, decoded with
    pyidotmatrix/btsnoop.py): this docstring used to read the tag rule out of
    TextAgreement.java ~line 1168 as "data.length == 64 -> tag 5, else tag 6".
    The else-branch value is WRONG. The app drove our panel with the 8x16 cell
    -- 16 bytes per glyph -- and those glyphs carried tag 0x02, not 6. Bit
    order and everything else matched byte-for-byte. Hence glyph_height and
    _SEPARATOR_TAGS above; 6 survives only as the fallback for cell sizes
    nobody has ever observed.

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
    if glyph_height not in _GLYPH_CELLS:
        raise ValueError(f"glyph_height must be one of {sorted(_GLYPH_CELLS)}, got {glyph_height!r}")

    bitmaps = _text_to_bitmaps(text, font_path, font_size, _GLYPH_CELLS[glyph_height])
    bg_mode = 0 if bg_color is None else 1
    resolved_bg = bg_color if bg_color is not None else (0, 0, 0)

    fg = list(color)
    if fg[0] == 0 and fg[1] == 0 and fg[2] == 0:
        fg[2] = 1  # device quirk: pure-black foreground would be invisible text

    metadata = bytearray([0, 0, 1, 1, text_mode, speed, color_mode, *fg, bg_mode, *resolved_bg])
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


def _text_to_bitmaps(
    text: str,
    font_path: str,
    font_size: int,
    cell: tuple[int, int] = (_CHAR_WIDTH, _CHAR_HEIGHT),
) -> bytearray:
    """Renders each character to a separator-prefixed 1-bit bitmap.

    cell is (width, height) in pixels; the separator tag follows from the
    packed size (see _SEPARATOR_TAGS). Bit order is row-major, LSB-first,
    byte-aligned -- identical for both cell sizes (capture-confirmed).
    """
    cell_width, cell_height = cell
    separator = bytes([_separator_tag(cell_width * cell_height // 8), 0xFF, 0xFF, 0xFF])
    font = ImageFont.truetype(font_path, font_size)
    stream = bytearray()
    for char in text:
        image = Image.new("1", (cell_width, cell_height), 0)
        draw = ImageDraw.Draw(image)
        _, _, text_width, text_height = draw.textbbox((0, 0), char, font=font)
        draw.text(
            ((cell_width - text_width) // 2, (cell_height - text_height) // 2),
            char,
            fill=1,
            font=font,
        )
        stream.extend(separator + _pack_bitmap(image, cell))
    return stream


def _separator_tag(packed_size: int) -> int:
    """The per-glyph tag byte for a packed glyph of `packed_size` bytes."""
    return _SEPARATOR_TAGS.get(packed_size, _SEPARATOR_TAG_FALLBACK)


def _pack_bitmap(image: Image.Image, cell: tuple[int, int] = (_CHAR_WIDTH, _CHAR_HEIGHT)) -> bytearray:
    """Packs a 1-bit image into bytes, 8 pixels per byte, row by row."""
    cell_width, cell_height = cell
    bitmap = bytearray()
    byte = 0
    for y in range(cell_height):
        for x in range(cell_width):
            if x % 8 == 0:
                byte = 0
            pixel = cast(int, image.getpixel((x, y)))  # mode "1" bitmap: always an int
            byte |= (pixel & 1) << (x % 8)
            if x % 8 == 7 or x == cell_width - 1:
                bitmap.append(byte)
    return bitmap
