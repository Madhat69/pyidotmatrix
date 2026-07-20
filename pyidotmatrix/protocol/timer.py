"""Timer ("Add alarm") packet builders. Pure functions, no I/O.

Byte layouts originally came from decompiled-APK research
(docs/ALARM_BUZZER_APK_FINDINGS.md in the research lab). HARDWARE-CONFIRMED
2026-07-12 on a real 32x32 panel: the 24-byte sendData header is ALL
little-endian (packet length and duration, previously guessed big-endian,
both proved wrong on the device -- see _build_timer_data_header). Up to 10
alarm slots (num 0-9); each fires a custom image/GIF/text at hour:minute for
a fixed duration, optionally with the buzzer.

CONFIRMED: content must be an encoded file (e.g. a real GIF bytestream) with
CONTENT_GIF for the device to actually render it at fire time.

CONTENT_IMAGE content format is CONFIRMED-FROM-SOURCE (docs/APK_SECOND_PASS.md,
Q2, AddTimerDialog.java:718 + BGRUtils.bitmap2RGB): raw, uncompressed RGB, no
header -- exactly width*height*3 bytes, row-major, [R,G,B] per pixel. This is
byte-identical to what the app's own image-alarm path sends. Our one hardware
test of this path (2026-07-12) used a payload whose duration header was
accidentally big-endian (a bug in that test, fixed since -- see
_build_timer_data_header's little-endian header), so the content was accepted
and saved (TimerAck status=3 SAVED) but is UNVERIFIED-PENDING-RETEST for
rendering -- do not treat that result as CONTENT_IMAGE being broken; retest
with a correct little-endian header and a payload sized exactly
panel_w * panel_h * 3 before drawing any conclusion about whether it renders.

CONFIRMED: at fire time the panel shows the clock for a few seconds before
the alarm's content appears -- expected, not a bug.

The chunked upload (sendData) reuses the same 4096-byte outer chunk + BLE-split
pipeline as protocol/gif.py -- see bytes_.chunk_by_size / split_into_ble_packets.
"""

import binascii
from collections.abc import Iterable
from dataclasses import dataclass

from pyidotmatrix.protocol import bytes_
from pyidotmatrix.validation import validate_byte

# Content-type wire byte (header offset 10). Named after the UI type it maps
# from: image (UI type 0) -> 2, GIF (UI type 1) -> 1, text (UI type 2) -> 3.
CONTENT_GIF = 1
CONTENT_IMAGE = 2
CONTENT_TEXT = 3
_CONTENT_TYPES = (CONTENT_GIF, CONTENT_IMAGE, CONTENT_TEXT)

# Duration bucket -> seconds the alarm's content stays on screen when it fires.
# Buckets and UI labels confirmed at AddTimerDialog.java:572-583.
DURATION_10S = 0
DURATION_30S = 1
DURATION_60S = 2
DURATION_300S = 3
DURATION_900S = 4

DURATION_SECONDS: dict[int, int] = {
    DURATION_10S: 10,
    DURATION_30S: 30,
    DURATION_60S: 60,
    DURATION_300S: 300,
    DURATION_900S: 900,
}

_TIMER_CLOSE_SIZE = 12
_TIMER_DATA_HEADER_SIZE = 24


@dataclass(frozen=True)
class Timer:
    """One of the device's 10 alarm slots.

    week is the raw day-of-week bitmask this command puts on the wire --
    unlike Schedule, Timer does NOT apply patch_week() to it (confirmed: zero
    matches for "patch" in the decompiled TimerAgreement.java). The bit
    meanings are now KNOWN, not just inferred (docs/APK_SECOND_PASS.md, Q3,
    traced from AddTimerDialog.java:424-433 + ByteUtils.getByteByArray):

        bit0 (LSB) = timer-enabled flag, NOT a day
        bit1 = Monday   bit2 = Tuesday  bit3 = Wednesday  bit4 = Thursday
        bit5 = Friday   bit6 = Saturday bit7 = Sunday (MSB)

    Use build_timer_week() to construct this value from weekday ints rather
    than hand-rolling the bit math. NOTE: this is the app's *encoding* of the
    byte, traced from source -- which physical day the device actually fires
    on for a given bit is still not hardware-verified per-day.
    """

    num: int
    week: int
    hour: int
    minute: int
    duration_bucket: int
    content_type: int
    buzzer_enable: bool

    def __post_init__(self):
        if not (0 <= self.num <= 9):
            raise ValueError(f"timer slot (num) must be 0..9, got {self.num}")
        validate_byte(self.week, "week")
        if not (0 <= self.hour <= 23):
            raise ValueError(f"hour must be 0..23, got {self.hour}")
        if not (0 <= self.minute <= 59):
            raise ValueError(f"minute must be 0..59, got {self.minute}")
        if self.duration_bucket not in DURATION_SECONDS:
            raise ValueError(f"duration_bucket must be 0..4, got {self.duration_bucket}")
        if self.content_type not in _CONTENT_TYPES:
            raise ValueError(f"content_type must be one of {_CONTENT_TYPES}, got {self.content_type}")


def build_timer_week(weekdays: Iterable[int], enabled: bool = True) -> int:
    """Builds a Timer wire week byte from weekday ints (Monday=0 .. Sunday=6,
    the same convention as datetime.weekday(), already used elsewhere in this
    package -- see protocol/common.py's build_set_time).

    Wire layout (docs/APK_SECOND_PASS.md, Q3): bit0 = enabled flag, bit1..7 =
    Mon..Sun. weekday d maps to bit (d + 1).
    """
    week = 1 if enabled else 0
    for day in weekdays:
        if not (0 <= day <= 6):
            raise ValueError(f"weekday must be 0..6 (Monday=0), got {day}")
        week |= 1 << (day + 1)
    return week


def build_timer_close(timer: Timer) -> bytearray:
    """Disables timer slot `timer.num` without deleting it (sendCloseData).

    Flat 12-byte packet, no chunking, no payload:
    [12, 0, 0x00, 0x80, num, week, hour, minute, dur_lo, dur_hi, content_type, buzzer]

    HARDWARE-CONFIRMED 2026-07-12: this little-endian duration is correct --
    the command was acked and the alarm behaved as expected. This also
    resolves the previous close/data endianness inconsistency: the sendData
    24-byte header's duration field is little-endian too (see
    _build_timer_data_header), so both fields now agree.
    """
    duration_seconds = DURATION_SECONDS[timer.duration_bucket]
    packet = bytearray(_TIMER_CLOSE_SIZE)
    packet[0] = _TIMER_CLOSE_SIZE
    packet[1] = 0
    packet[2] = 0x00
    packet[3] = 0x80
    packet[4] = timer.num
    packet[5] = timer.week
    packet[6] = timer.hour
    packet[7] = timer.minute
    packet[8:10] = duration_seconds.to_bytes(2, "little")  # dur_lo, dur_hi (confirmed LE on hardware)
    packet[10] = timer.content_type
    packet[11] = 1 if timer.buzzer_enable else 0
    return packet


def build_timer_data_packets(timer: Timer, payload: bytes) -> list[list[bytearray]]:
    """Builds the BLE packets for an alarm's custom content (sendData).

    Mirrors protocol/gif.py's build_packets: 4096-byte outer chunks, each
    prefixed with a 24-byte header, then split into BLE-sized packets.

    HARDWARE-CONFIRMED 2026-07-12 (ack behavior): when the payload fits in a
    single outer chunk, the device goes straight to TimerAck status=3 SAVED --
    it does not send a status=1 NEXT_CHUNK ack first. TimerAck frames can also
    arrive DUPLICATED (the same status observed twice for one chunk); callers
    should tolerate repeats rather than treating a second ack as an error. A
    flat close (build_timer_close) returns a TimerAck whose status echoes the
    slot's current save-state: 1 was observed closing an empty/unsaved slot,
    3 after content had been saved to it.
    """
    if not payload:
        raise ValueError("payload cannot be empty")

    def header_builder(chunk: bytearray, full_payload: bytes, is_first: bool) -> bytes:
        return _build_timer_data_header(chunk, full_payload, timer, is_first)

    return bytes_.build_chunked_packets(payload, header_builder)


def _build_timer_data_header(chunk: bytearray, payload: bytes, timer: Timer, is_first: bool) -> bytes:
    """The 24-byte header prefixed to each 4K chunk of a Timer sendData upload.

    HARDWARE-CONFIRMED 2026-07-12: this header is ALL little-endian, including
    packet length and duration (both previously guessed big-endian). A
    big-endian length made the device go silent (no ack at all); little-endian
    length got a TimerAck SAVED. A big-endian duration made the device fall
    back to its 10s default; little-endian duration produced the correct 30s
    behavior. Total-payload-length and CRC were already little-endian and were
    correct all along.
    """
    duration_seconds = DURATION_SECONDS[timer.duration_bucket]
    header = bytearray(_TIMER_DATA_HEADER_SIZE)
    header[0:2] = (len(chunk) + _TIMER_DATA_HEADER_SIZE).to_bytes(2, "little")  # packet length, LE (confirmed)
    header[2] = 0x00
    header[3] = 0x80
    header[4] = timer.num
    header[5] = timer.week  # raw, unpatched -- patch() is Schedule-only
    header[6] = timer.hour
    header[7] = timer.minute
    header[8:10] = duration_seconds.to_bytes(2, "little")  # duration seconds, LE (confirmed)
    header[10] = timer.content_type
    header[11] = 1 if timer.buzzer_enable else 0
    header[12] = 0 if is_first else 2  # first vs continuation
    header[13:17] = bytes_.int_to_bytes_le(len(payload))  # total payload length, LE
    header[17:21] = bytes_.int_to_bytes_le(binascii.crc32(payload) & 0xFFFFFFFF)  # CRC32, LE
    header[21:23] = b"\x00\x00"
    header[23] = (timer.num + 20) & 0xFF  # second marker, purpose unclear (see doc)
    return bytes(header)
