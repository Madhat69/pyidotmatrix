"""Weekly Schedule ("themes") packet builders. Pure functions, no I/O.

EXPERIMENTAL: byte layouts come from decompiled-APK research
(docs/ALARM_BUZZER_APK_FINDINGS.md in the research lab), never exercised
against real hardware. A schedule theme is a recurring window (day-of-week
bitmask + start/end time) that shows custom content, with one master on/off
switch shared across all themes.

The chunked upload reuses the same 4096-byte outer chunk + BLE-split pipeline
as protocol/gif.py / protocol/timer.py -- see bytes_.chunk_by_size /
split_into_ble_packets.
"""

import binascii
from dataclasses import dataclass

from idotmatrix.protocol import bytes_
from idotmatrix.validation import validate_byte

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


def patch_week(week: int) -> int:
    """The APK's week-bitmask transform (ScheduleAgreement.patch, lines 218-227).

    Takes week as an 8-char binary string, drops the MSB char, appends "1", and
    reparses as binary -- equivalent to ((week << 1) | 1) & 0xFF. The resulting
    day-of-week mapping is EMPIRICALLY UNVERIFIED: which day-checkbox selection
    produces which raw `week` int, and what day the device actually fires the
    schedule on after this transform, both need a hardware table before this can
    be trusted. Do not rely on this for anything beyond format-parity testing.
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

    chunks = bytes_.chunk_by_size(payload, bytes_.CHUNK_SIZE_4096)
    return [
        bytes_.split_into_ble_packets(
            _build_theme_header(chunk, payload, theme, content, is_first=index == 0) + chunk
        )
        for index, chunk in enumerate(chunks)
    ]


def _build_theme_header(chunk: bytearray, payload: bytes, theme: ScheduleTheme, content: int, is_first: bool) -> bytes:
    """The 23-byte header prefixed to each 4K chunk of a Schedule theme upload."""
    header = bytearray(_THEME_HEADER_SIZE)
    header[0:2] = (len(chunk) + _THEME_HEADER_SIZE).to_bytes(2, "big")  # packet length, BE
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
