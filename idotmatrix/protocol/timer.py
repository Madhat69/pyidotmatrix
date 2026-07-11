"""Timer ("Add alarm") packet builders. Pure functions, no I/O.

EXPERIMENTAL: byte layouts come from decompiled-APK research
(docs/ALARM_BUZZER_APK_FINDINGS.md in the research lab), never exercised
against real hardware. Up to 10 alarm slots (num 0-9); each fires a custom
image/GIF/text at hour:minute for a fixed duration, optionally with the buzzer.

The chunked upload (sendData) reuses the same 4096-byte outer chunk + BLE-split
pipeline as protocol/gif.py -- see bytes_.chunk_by_size / split_into_ble_packets.
"""

import binascii
from dataclasses import dataclass

from idotmatrix.protocol import bytes_
from idotmatrix.validation import validate_byte

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

    week is the raw day-of-week bitmask as understood by the device -- unlike
    Schedule, Timer does NOT apply patch_week() to it (confirmed in the doc:
    "bitmask, unpatched (see Schedule's patch() below -- Timer does NOT call
    patch)").
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


def build_timer_close(timer: Timer) -> bytearray:
    """Disables timer slot `timer.num` without deleting it (sendCloseData).

    Flat 12-byte packet, no chunking, no payload:
    [12, 0, 0x00, 0x80, num, week, hour, minute, dur_lo, dur_hi, content_type, buzzer]

    NOTE: endianness unverified on hardware. The doc's flat sendCloseData layout
    names this field dur_lo/dur_hi (little-endian byte order), while the chunked
    sendData 24-byte header explicitly states the same logical duration field is
    big-endian. Each is transcribed here exactly as its own doc section states --
    do not assume the two match without a live capture.
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
    packet[8:10] = duration_seconds.to_bytes(2, "little")  # dur_lo, dur_hi (unverified endianness)
    packet[10] = timer.content_type
    packet[11] = 1 if timer.buzzer_enable else 0
    return packet


def build_timer_data_packets(timer: Timer, payload: bytes) -> list[list[bytearray]]:
    """Builds the BLE packets for an alarm's custom content (sendData).

    Mirrors protocol/gif.py's build_packets: 4096-byte outer chunks, each
    prefixed with a 24-byte header, then split into BLE-sized packets.
    """
    if not payload:
        raise ValueError("payload cannot be empty")

    chunks = bytes_.chunk_by_size(payload, bytes_.CHUNK_SIZE_4096)
    return [
        bytes_.split_into_ble_packets(_build_timer_data_header(chunk, payload, timer, is_first=index == 0) + chunk)
        for index, chunk in enumerate(chunks)
    ]


def _build_timer_data_header(chunk: bytearray, payload: bytes, timer: Timer, is_first: bool) -> bytes:
    """The 24-byte header prefixed to each 4K chunk of a Timer sendData upload."""
    duration_seconds = DURATION_SECONDS[timer.duration_bucket]
    header = bytearray(_TIMER_DATA_HEADER_SIZE)
    header[0:2] = (len(chunk) + _TIMER_DATA_HEADER_SIZE).to_bytes(2, "big")  # packet length, BE
    header[2] = 0x00
    header[3] = 0x80
    header[4] = timer.num
    header[5] = timer.week  # raw, unpatched -- patch() is Schedule-only
    header[6] = timer.hour
    header[7] = timer.minute
    header[8:10] = duration_seconds.to_bytes(2, "big")  # duration seconds, BE
    header[10] = timer.content_type
    header[11] = 1 if timer.buzzer_enable else 0
    header[12] = 0 if is_first else 2  # first vs continuation
    header[13:17] = bytes_.int_to_bytes_le(len(payload))  # total payload length, LE
    header[17:21] = bytes_.int_to_bytes_le(binascii.crc32(payload) & 0xFFFFFFFF)  # CRC32, LE
    header[21:23] = b"\x00\x00"
    header[23] = (timer.num + 20) & 0xFF  # second marker, purpose unclear (see doc)
    return bytes(header)
