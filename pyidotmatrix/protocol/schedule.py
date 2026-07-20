"""Weekly Schedule ("themes") packet builders. Pure functions, no I/O.

EXPERIMENTAL: byte layouts come from decompiled-APK research
(docs/ALARM_BUZZER_APK_FINDINGS.md in the research lab). A schedule theme is a
recurring window (day-of-week bitmask + start/end time) that shows custom
content, with one master on/off switch shared across all themes.

HARDWARE-CONFIRMED 2026-07-12: the per-theme chunked upload's ack
([5,0,5,0x80,status]) carries the same 1/3/0 status vocabulary as Timer's
sendData -- see protocol/response.py's StatusAck -- and a real upload on a
32x32 panel completed with status=3 SAVED, which is strong evidence the chunk
header format below (_build_theme_header) is correct. The day-of-week bitmask
encoding (patch_week) is now UNDERSTOOD at the source level (see patch_week's
docstring, docs/APK_SECOND_PASS.md Q3) -- it's a layout conversion from this
module's RAW week byte into Timer's wire format, day mapping derivable. What
remains unverified: which physical day the device actually fires on for a
given bit (no hardware table yet), and whether the saved content actually
renders during its active window (see probes/probe_schedule_gif.py).

CONTENT_IMAGE content format is CONFIRMED-FROM-SOURCE (docs/APK_SECOND_PASS.md,
Q2, NewScheduleThemeDialog.java:400 + BGRUtils.bitmapByte) and is a genuine,
source-confirmed asymmetry with Timer: Schedule's IMAGE content is a
single-frame PNG (Bitmap.CompressFormat.PNG, quality 100), NOT raw RGB like
Timer's CONTENT_IMAGE. Hardware-untested -- send PNG-encoded bytes, not raw
pixels, when using CONTENT_IMAGE here.

The chunked upload reuses the same 4096-byte outer chunk + BLE-split pipeline
as protocol/gif.py / protocol/timer.py -- see bytes_.chunk_by_size /
split_into_ble_packets.
"""

import binascii
from collections.abc import Iterable
from dataclasses import dataclass

from pyidotmatrix.protocol import bytes_
from pyidotmatrix.validation import validate_byte

# Per-theme content-type wire byte (header offset 10). Schedule's textSolve
# byte layout is not trustworthy from the decompile (see build_schedule_text_packets)
# so only gif/image are supported here.
CONTENT_GIF = 1
CONTENT_IMAGE = 2
_CONTENT_TYPES = (CONTENT_GIF, CONTENT_IMAGE)

_MASTER_SWITCH_SIZE = 5
_THEME_HEADER_SIZE = 23


@dataclass(frozen=True)
class ScheduleTheme:
    """One weekly-schedule theme: a recurring day/time window with content.

    week is the raw day-of-week bitmask as selected in the UI, BEFORE
    patch_week() -- build_schedule_theme_packets applies patch_week() itself.
    RAW (pre-patch) layout (docs/APK_SECOND_PASS.md, Q3, traced from
    BleProtocol.java's convertWeekByte): bits0..6 = Mon..Sun, bit7 =
    "not repeating" flag (the UI's separate no-specific-day toggle, discarded
    by patch_week -- see its docstring). Use build_schedule_week() to
    construct this value from weekday ints rather than hand-rolling the bit
    math.
    """

    index: int
    week: int
    start_hour: int
    start_min: int
    end_hour: int
    end_min: int

    def __post_init__(self):
        validate_byte(self.index, "index")
        validate_byte(self.week, "week")
        if not (0 <= self.start_hour <= 23):
            raise ValueError(f"start_hour must be 0..23, got {self.start_hour}")
        if not (0 <= self.end_hour <= 23):
            raise ValueError(f"end_hour must be 0..23, got {self.end_hour}")
        if not (0 <= self.start_min <= 59):
            raise ValueError(f"start_min must be 0..59, got {self.start_min}")
        if not (0 <= self.end_min <= 59):
            raise ValueError(f"end_min must be 0..59, got {self.end_min}")


def build_schedule_week(weekdays: Iterable[int], repeating: bool = True) -> int:
    """Builds a Schedule RAW (pre-patch) week byte from weekday ints
    (Monday=0 .. Sunday=6, matching build_timer_week and datetime.weekday()).

    RAW layout (docs/APK_SECOND_PASS.md, Q3): bits0..6 = Mon..Sun, bit7 =
    "not repeating" flag. weekday d maps to bit d. repeating=False sets bit7
    instead of any day bits, mirroring the UI's separate no-specific-day
    toggle (weekVOList[7]) -- pass an empty weekdays iterable in that case, as
    the UI does. Feed the result to patch_week() before putting it on the wire
    (build_schedule_theme_packets does this for you).
    """
    week = (1 << 7) if not repeating else 0
    for day in weekdays:
        if not (0 <= day <= 6):
            raise ValueError(f"weekday must be 0..6 (Monday=0), got {day}")
        week |= 1 << day
    return week


def patch_week(week: int) -> int:
    """Converts a Schedule RAW (pre-patch) week byte -- see build_schedule_week
    -- into Timer's wire layout (ScheduleAgreement.patch, lines 218-227).

    Semantics are now UNDERSTOOD, not just an opaque bit-twiddle
    (docs/APK_SECOND_PASS.md, Q3): character-by-character tracing of patch()
    shows it takes the RAW byte's bits [b7 b6 b5 b4 b3 b2 b1 b0], drops b7 (the
    "not repeating" flag) and appends a constant 1 as the new bit0 (enabled
    flag) -- i.e. [b6 b5 b4 b3 b2 b1 b0 1], equivalent to
    ((week << 1) | 1) & 0xFF. This is exactly a layout conversion from
    Schedule's RAW storage format into Timer's wire format (bit0=enabled,
    bit1..7=Mon..Sun) -- confirming why Timer never calls patch(): its week
    byte is already in the post-patch shape. Day mapping is therefore
    derivable (Monday=RAW bit0 -> patched bit1, ... Sunday=RAW bit6 -> patched
    bit7), same as Timer's. NOTE: this is the app's *encoding*, traced from
    source -- which physical day the device actually fires on for a given bit
    is still not hardware-verified per-day.

    The APK's own patch() has a probable off-by-one when no day is selected
    (week=0x80, "not repeating"): it unsigns the byte via `number + 255`
    instead of `+ 256` before converting to binary, which turns 0x80
    (-128 as a sign-extended Java int) into 0xFF (every day flagged) instead
    of the mathematically-intended 0x01 (enabled-bit only, no days) --
    UNRESOLVED whether that's by design. Our implementation here is a direct
    bitwise shift over an already-validated 0..255 Python int (validate_byte
    above) -- there is no sign-extension step, so it does NOT reproduce that
    bug: patch_week(0x80) correctly returns 0x01 here (verified by hand and by
    test_patch_week_matches_formula's direct-formula check against every week
    value 0..255), where the app's buggy Java would instead produce 0xFF for
    the same input.
    """
    validate_byte(week, "week")
    return ((week << 1) | 1) & 0xFF


def build_master_switch(enable: bool, buzzer: bool) -> bytearray:
    """Schedule.masterSwitch(enable, buzzer): a single 5-byte command, no chunking.

    [5, 0, 7, 0x80, packed] where packed is built by the APK's reverse-order bit
    packer (ByteUtils.getByteByArray/bitToByte) over {enable, buzzer, 0,0,0,0,0,0},
    which works out to (buzzer << 1) | enable -- i.e. enable is bit 0, buzzer is
    bit 1. Bit order is derived from the decompiled packer, not observed on a real
    device; verify on hardware.
    """
    packed = ((1 if buzzer else 0) << 1) | (1 if enable else 0)
    return bytearray([_MASTER_SWITCH_SIZE, 0, 7, 0x80, packed])


def build_schedule_theme_packets(theme: ScheduleTheme, payload: bytes, content: int) -> list[list[bytearray]]:
    """Builds the BLE packets for one schedule theme's gif/image content.

    content must be CONTENT_GIF or CONTENT_IMAGE (Schedule's textSolve is not
    ported -- see build_schedule_text_packets). Mirrors protocol/gif.py's
    build_packets: 4096-byte outer chunks, each prefixed with a 23-byte header,
    then split into BLE-sized packets.
    """
    if not payload:
        raise ValueError("payload cannot be empty")
    if content not in _CONTENT_TYPES:
        raise ValueError(f"content must be one of {_CONTENT_TYPES}, got {content}")

    def header_builder(chunk: bytearray, full_payload: bytes, is_first: bool) -> bytes:
        return _build_theme_header(chunk, full_payload, theme, content, is_first)

    return bytes_.build_chunked_packets(payload, header_builder)


def _build_theme_header(chunk: bytearray, payload: bytes, theme: ScheduleTheme, content: int, is_first: bool) -> bytes:
    """The 23-byte header prefixed to each 4K chunk of a Schedule theme upload."""
    header = bytearray(_THEME_HEADER_SIZE)
    # packet length, LE: originally only INFERRED from the Timer hardware result
    # (2026-07-12), which falsified the same big-endian-length assumption from
    # the same doc source for Timer's 24-byte header. Now corroborated: a real
    # Schedule theme upload using this header completed with StatusAck status=3
    # SAVED on hardware the same day (see module docstring).
    header[0:2] = (len(chunk) + _THEME_HEADER_SIZE).to_bytes(2, "little")
    header[2] = 5  # Schedule-family type constant (vs. Timer's 0x00)
    header[3] = 0x80
    header[4] = theme.index
    header[5] = patch_week(theme.week)
    header[6] = theme.start_hour
    header[7] = theme.start_min
    header[8] = theme.end_hour
    header[9] = theme.end_min
    header[10] = content
    header[11] = 0 if is_first else 2  # first vs continuation
    header[12:16] = bytes_.int_to_bytes_le(len(payload))  # total payload length, LE
    header[16:20] = bytes_.int_to_bytes_le(binascii.crc32(payload) & 0xFFFFFFFF)  # CRC32, LE
    header[20:22] = b"\x00\x00"
    header[22] = (theme.index + 30) & 0xFF  # second marker, disjoint range from Timer's num+20
    return bytes(header)


def build_schedule_text_packets(*_args, **_kwargs):
    """NOT PORTED: Schedule's textSolve byte offsets are untrustworthy.

    The decompiled ScheduleAgreement.textSolve (lines 278-487) reuses obfuscated
    local variables (c, c2, c3... c10) as aliases for plain ints across branches
    in a way that is very easy to misread by eye -- the doc explicitly warns not
    to hand-transcribe it. Re-derive the real header from a live BLE capture
    instead. See docs/ALARM_BUZZER_APK_FINDINGS.md ("textSolve... do not trust
    the byte offsets read directly off this method").
    """
    raise NotImplementedError(
        "Schedule text upload is not ported: textSolve's byte offsets are untrustworthy in the "
        "decompile (see docs/ALARM_BUZZER_APK_FINDINGS.md) and must be re-derived from a live "
        "BLE capture, not hand-transcribed."
    )
