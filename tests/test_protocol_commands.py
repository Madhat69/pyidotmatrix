"""Golden tests for the native command builders.

Every value here was proven byte-identical to the original lab implementation
before being pinned (see the parity check run during development).
"""

from datetime import datetime

import pytest

from pyidotmatrix.protocol import (
    chronograph,
    clock,
    common,
    countdown,
    eco,
    effect,
    fullscreen_color,
    music_sync,
    scoreboard,
)


def test_chronograph():
    assert chronograph.build_set_mode(1) == bytearray([5, 0, 9, 128, 1])
    with pytest.raises(ValueError):
        chronograph.build_set_mode(4)


def test_countdown():
    assert countdown.build_set_mode(1, 25, 0) == bytearray([7, 0, 8, 128, 1, 25, 0])
    with pytest.raises(ValueError):
        countdown.build_set_mode(1, 60, 0)


def test_clock_flags():
    # style 3, show_date + hour24 -> 3 | 128 | 64 = 195
    assert clock.build_show(3, True, True, (10, 20, 30)) == bytearray([8, 0, 6, 1, 195, 10, 20, 30])
    assert clock.build_show(0, False, False, (0, 0, 0))[4] == 0


def test_scoreboard_little_endian_and_clamp():
    assert scoreboard.build_show(12, 5) == bytearray([8, 0, 10, 128, 12, 0, 5, 0])
    # 9999 clamps to 999 = 0x03E7 -> LSB 0xE7, MSB 0x03
    assert scoreboard.build_show(9999, 0)[4:6] == bytearray([0xE7, 0x03])


def test_eco():
    assert eco.build_set_mode(True, 22, 0, 6, 0, 10) == bytearray([10, 0, 2, 128, 1, 22, 0, 6, 0, 10])


def test_fullscreen_color():
    assert fullscreen_color.build_show_color((1, 2, 3)) == bytearray([7, 0, 2, 2, 1, 2, 3])


def test_effect_length_fields_count_colors():
    payload = effect.build_show(1, [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    assert payload[0] == 6 + 3  # colors, not components
    assert payload[6] == 3
    assert payload[7:] == bytearray([255, 0, 0, 0, 255, 0, 0, 0, 255])


def test_music_sync():
    assert music_sync.build_set_mic_type(2) == bytearray([6, 0, 11, 128, 2])
    assert music_sync.build_send_image_rhythm(5) == bytearray([6, 0, 0, 2, 5, 1])
    assert music_sync.build_stop_rhythm() == bytearray([6, 0, 0, 2, 0, 0])


def test_common_time_and_flip():
    when = datetime(2026, 7, 11, 20, 30, 15)
    payload = common.build_set_time(when)
    assert payload[:8] == bytearray([11, 0, 1, 128, 26, 7, 11, when.weekday() + 1])
    assert payload[8:] == bytearray([20, 30, 15])
    assert common.build_set_screen_flipped(True) == bytearray([5, 0, 6, 128, 1])


def test_common_reset_is_packet_structure():
    assert common.build_reset() == [[bytearray.fromhex("04 00 03 80")]]
