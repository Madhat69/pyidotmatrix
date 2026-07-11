"""Tests for the EXPERIMENTAL Timer and Schedule protocol modules.

Byte layouts come from decompiled-APK research (see docs/ALARM_BUZZER_APK_FINDINGS.md
in the research lab) and are unverified on hardware -- these tests pin the
*transcription* of that research, not device-confirmed behavior.
"""

import binascii

import pytest

from idotmatrix.protocol import schedule, timer
from idotmatrix.protocol.response import DeviceAck, TimerAck, parse_response


def _flatten(chunk_packets: list) -> bytes:
    """Concatenates one outer chunk's BLE-sized packets back into raw bytes."""
    return b"".join(bytes(p) for p in chunk_packets)


# --- Timer: build_timer_close ---------------------------------------------


def test_timer_close_payload():
    t = timer.Timer(
        num=3,
        week=170,
        hour=7,
        minute=30,
        duration_bucket=timer.DURATION_60S,
        content_type=timer.CONTENT_IMAGE,
        buzzer_enable=True,
    )
    assert timer.build_timer_close(t) == bytearray([12, 0, 0x00, 0x80, 3, 170, 7, 30, 60, 0, 2, 1])


def test_timer_close_duration_little_endian_and_buzzer_off():
    # duration_bucket 4 -> 900s -> needs both bytes; buzzer off -> last byte 0.
    t = timer.Timer(
        num=0,
        week=0,
        hour=0,
        minute=0,
        duration_bucket=timer.DURATION_900S,
        content_type=timer.CONTENT_GIF,
        buzzer_enable=False,
    )
    packet = timer.build_timer_close(t)
    assert packet[8:10] == (900).to_bytes(2, "little")  # dur_lo, dur_hi
    assert packet[10] == timer.CONTENT_GIF
    assert packet[11] == 0


# --- Timer: build_timer_data_packets --------------------------------------


def test_timer_data_header_small_payload():
    t = timer.Timer(
        num=5,
        week=1,
        hour=13,
        minute=45,
        duration_bucket=timer.DURATION_300S,
        content_type=timer.CONTENT_GIF,
        buzzer_enable=False,
    )
    payload = bytes(range(100))  # < 4096: single chunk
    packets = timer.build_timer_data_packets(t, payload)
    assert len(packets) == 1

    raw = _flatten(packets[0])
    header, body = raw[:24], raw[24:]
    assert body == payload
    assert header[0:2] == (100 + 24).to_bytes(2, "big")  # packet length, BE
    assert header[2] == 0x00
    assert header[3] == 0x80
    assert header[4] == 5  # num
    assert header[5] == 1  # week, raw/unpatched
    assert header[6] == 13  # hour
    assert header[7] == 45  # minute
    assert header[8:10] == (300).to_bytes(2, "big")  # duration seconds, BE
    assert header[10] == timer.CONTENT_GIF
    assert header[11] == 0  # buzzer off
    assert header[12] == 0  # first chunk
    assert header[13:17] == (100).to_bytes(4, "little")  # total payload length, LE
    assert header[17:21] == binascii.crc32(payload).to_bytes(4, "little")  # CRC32, LE
    assert header[21:23] == b"\x00\x00"
    assert header[23] == 5 + 20  # num + 20


def test_timer_data_header_multi_chunk_continuation():
    t = timer.Timer(
        num=9,
        week=255,
        hour=23,
        minute=59,
        duration_bucket=timer.DURATION_10S,
        content_type=timer.CONTENT_TEXT,
        buzzer_enable=True,
    )
    payload = bytes((i * 7) % 256 for i in range(5000))  # > 4096: two chunks
    packets = timer.build_timer_data_packets(t, payload)
    assert len(packets) == 2

    total_crc = binascii.crc32(payload) & 0xFFFFFFFF
    expected_chunk_sizes = [4096, 904]
    for chunk_index, (chunk_packets, chunk_size) in enumerate(zip(packets, expected_chunk_sizes)):
        raw = _flatten(chunk_packets)
        header, body = raw[:24], raw[24:]
        assert len(body) == chunk_size
        assert header[0:2] == (chunk_size + 24).to_bytes(2, "big")
        assert header[4] == 9
        assert header[5] == 255
        assert header[6] == 23
        assert header[7] == 59
        assert header[8:10] == (10).to_bytes(2, "big")
        assert header[10] == timer.CONTENT_TEXT
        assert header[11] == 1  # buzzer on
        assert header[12] == (0 if chunk_index == 0 else 2)  # continuation flag
        assert header[13:17] == len(payload).to_bytes(4, "little")  # same total on every chunk
        assert header[17:21] == total_crc.to_bytes(4, "little")  # same CRC on every chunk
        assert header[21:23] == b"\x00\x00"
        assert header[23] == 9 + 20


def test_timer_data_packets_rejects_empty_payload():
    t = timer.Timer(
        num=0, week=0, hour=0, minute=0,
        duration_bucket=timer.DURATION_10S, content_type=timer.CONTENT_GIF, buzzer_enable=False,
    )
    with pytest.raises(ValueError):
        timer.build_timer_data_packets(t, b"")


# --- Timer: duration table / content-type mapping -------------------------


def test_duration_seconds_table():
    assert timer.DURATION_SECONDS == {
        timer.DURATION_10S: 10,
        timer.DURATION_30S: 30,
        timer.DURATION_60S: 60,
        timer.DURATION_300S: 300,
        timer.DURATION_900S: 900,
    }


def test_content_type_wire_values():
    assert timer.CONTENT_GIF == 1
    assert timer.CONTENT_IMAGE == 2
    assert timer.CONTENT_TEXT == 3


# --- Timer: validation ------------------------------------------------------


def _valid_timer_kwargs(**overrides):
    base = dict(
        num=0, week=0, hour=0, minute=0,
        duration_bucket=timer.DURATION_10S, content_type=timer.CONTENT_GIF, buzzer_enable=False,
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "overrides",
    [
        {"num": -1},
        {"num": 10},
        {"hour": 24},
        {"hour": -1},
        {"minute": 60},
        {"minute": -1},
        {"duration_bucket": 5},
        {"duration_bucket": -1},
        {"week": 256},
        {"week": -1},
        {"content_type": 0},
        {"content_type": 4},
    ],
)
def test_timer_rejects_out_of_range(overrides):
    with pytest.raises(ValueError):
        timer.Timer(**_valid_timer_kwargs(**overrides))


def test_timer_accepts_boundary_values():
    # Regression guard: valid edges must not raise.
    timer.Timer(**_valid_timer_kwargs(num=9, hour=23, minute=59, duration_bucket=4, week=255))
    timer.Timer(**_valid_timer_kwargs(num=0, hour=0, minute=0, duration_bucket=0, week=0))


# --- Schedule: patch_week ----------------------------------------------------


@pytest.mark.parametrize(
    "week,expected",
    [
        (0, 1),
        (1, 3),
        (0xFF, 0xFF),
        (127, 255),
        (0b1010101, ((0b1010101 << 1) | 1) & 0xFF),
    ],
)
def test_patch_week_table(week, expected):
    assert schedule.patch_week(week) == expected


@pytest.mark.parametrize("week", range(0, 256, 17))
def test_patch_week_matches_formula(week):
    assert schedule.patch_week(week) == ((week << 1) | 1) & 0xFF


def test_patch_week_rejects_out_of_range():
    with pytest.raises(ValueError):
        schedule.patch_week(256)
    with pytest.raises(ValueError):
        schedule.patch_week(-1)


# --- Schedule: build_master_switch -------------------------------------------


@pytest.mark.parametrize(
    "enable,buzzer,expected_packed",
    [
        (False, False, 0b00),
        (True, False, 0b01),
        (False, True, 0b10),
        (True, True, 0b11),
    ],
)
def test_master_switch_payload(enable, buzzer, expected_packed):
    assert schedule.build_master_switch(enable, buzzer) == bytearray([5, 0, 7, 0x80, expected_packed])


# --- Schedule: build_schedule_theme_packets ----------------------------------


def test_schedule_theme_header_gif_small_payload():
    theme = schedule.ScheduleTheme(index=2, week=5, start_hour=6, start_min=0, end_hour=8, end_min=30)
    payload = bytes(range(50))
    packets = schedule.build_schedule_theme_packets(theme, payload, schedule.CONTENT_GIF)
    assert len(packets) == 1

    raw = _flatten(packets[0])
    header, body = raw[:23], raw[23:]
    assert body == payload
    assert header[0:2] == (50 + 23).to_bytes(2, "big")
    assert header[2] == 5  # Schedule-family type constant
    assert header[3] == 0x80
    assert header[4] == 2  # index
    assert header[5] == schedule.patch_week(5)  # week is patched for the wire
    assert header[6] == 6  # start_hour
    assert header[7] == 0  # start_min
    assert header[8] == 8  # end_hour
    assert header[9] == 30  # end_min
    assert header[10] == schedule.CONTENT_GIF
    assert header[11] == 0  # first chunk
    assert header[12:16] == (50).to_bytes(4, "little")
    assert header[16:20] == binascii.crc32(payload).to_bytes(4, "little")
    assert header[20:22] == b"\x00\x00"
    assert header[22] == 2 + 30  # index + 30


def test_schedule_theme_header_image_multi_chunk_continuation():
    theme = schedule.ScheduleTheme(index=7, week=170, start_hour=0, start_min=0, end_hour=23, end_min=59)
    payload = bytes((i * 3) % 256 for i in range(4200))  # > 4096: two chunks
    packets = schedule.build_schedule_theme_packets(theme, payload, schedule.CONTENT_IMAGE)
    assert len(packets) == 2

    total_crc = binascii.crc32(payload) & 0xFFFFFFFF
    expected_chunk_sizes = [4096, 104]
    for chunk_index, (chunk_packets, chunk_size) in enumerate(zip(packets, expected_chunk_sizes)):
        raw = _flatten(chunk_packets)
        header, body = raw[:23], raw[23:]
        assert len(body) == chunk_size
        assert header[0:2] == (chunk_size + 23).to_bytes(2, "big")
        assert header[2] == 5
        assert header[3] == 0x80
        assert header[4] == 7
        assert header[5] == schedule.patch_week(170)
        assert header[10] == schedule.CONTENT_IMAGE
        assert header[11] == (0 if chunk_index == 0 else 2)
        assert header[12:16] == len(payload).to_bytes(4, "little")
        assert header[16:20] == total_crc.to_bytes(4, "little")
        assert header[20:22] == b"\x00\x00"
        assert header[22] == 7 + 30


def test_schedule_theme_packets_rejects_empty_payload():
    theme = schedule.ScheduleTheme(index=0, week=0, start_hour=0, start_min=0, end_hour=0, end_min=0)
    with pytest.raises(ValueError):
        schedule.build_schedule_theme_packets(theme, b"", schedule.CONTENT_GIF)


def test_schedule_theme_packets_rejects_bad_content():
    theme = schedule.ScheduleTheme(index=0, week=0, start_hour=0, start_min=0, end_hour=0, end_min=0)
    with pytest.raises(ValueError):
        schedule.build_schedule_theme_packets(theme, b"x", content=3)


def test_schedule_text_packets_not_implemented():
    with pytest.raises(NotImplementedError, match="ALARM_BUZZER_APK_FINDINGS"):
        schedule.build_schedule_text_packets()


# --- Schedule: validation -----------------------------------------------------


def _valid_theme_kwargs(**overrides):
    base = dict(index=0, week=0, start_hour=0, start_min=0, end_hour=0, end_min=0)
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "overrides",
    [
        {"week": 256},
        {"week": -1},
        {"start_hour": 24},
        {"start_hour": -1},
        {"end_hour": 24},
        {"end_hour": -1},
        {"start_min": 60},
        {"start_min": -1},
        {"end_min": 60},
        {"end_min": -1},
        {"index": 256},
        {"index": -1},
    ],
)
def test_schedule_theme_rejects_out_of_range(overrides):
    with pytest.raises(ValueError):
        schedule.ScheduleTheme(**_valid_theme_kwargs(**overrides))


# --- Response parsing: TimerAck vs. DeviceAck --------------------------------


@pytest.mark.parametrize(
    "status,expected_status",
    [
        (0, 0),  # failed
        (1, 1),  # next chunk
        (3, 3),  # saved
    ],
)
def test_timer_ack_parses_as_distinct_type(status, expected_status):
    ack = parse_response(bytes([0x05, 0x00, 0x00, 0x80, status]))
    assert isinstance(ack, TimerAck)
    assert not isinstance(ack, DeviceAck)
    assert ack.command_type == 0x00
    assert ack.command_subtype == 0x80
    assert ack.status == expected_status


def test_timer_ack_status_constants_match_doc():
    from idotmatrix.protocol.response import TIMER_STATUS_FAILED, TIMER_STATUS_NEXT_CHUNK, TIMER_STATUS_SAVED

    assert TIMER_STATUS_FAILED == 0
    assert TIMER_STATUS_NEXT_CHUNK == 1
    assert TIMER_STATUS_SAVED == 3


def test_schedule_master_switch_ack_still_parses_as_device_ack():
    # [5, 0, 7, 0x80, status] -- type=7, distinct from Timer's type=0x00.
    ack = parse_response(bytes.fromhex("0500078001"))
    assert isinstance(ack, DeviceAck)
    assert not isinstance(ack, TimerAck)
    assert ack.command_type == 7
    assert ack.command_subtype == 0x80
    assert ack.accepted is True


def test_schedule_theme_ack_still_parses_as_device_ack():
    # [5, 0, 5, 0x80, status] -- type=5, distinct from Timer's type=0x00.
    ack = parse_response(bytes.fromhex("0500058001"))
    assert isinstance(ack, DeviceAck)
    assert not isinstance(ack, TimerAck)
    assert ack.command_type == 5
    assert ack.command_subtype == 0x80
    assert ack.accepted is True


def test_ordinary_device_acks_are_unaffected():
    # Regression guard: an unrelated command's ack (brightness, type=4) must
    # still come back as a plain DeviceAck, exactly as before this change.
    ack = parse_response(bytes.fromhex("0500048001"))
    assert isinstance(ack, DeviceAck)
    assert ack.command_type == 0x04
    assert ack.accepted is True
