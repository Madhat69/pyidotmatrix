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


def test_effect_default_speed_is_byte_identical_to_legacy():
    # The lab-era builder hardcoded speed=90; the default must not change the wire bytes.
    payload = effect.build_show(1, [(255, 0, 0), (0, 255, 0)])
    assert payload == bytearray([8, 0, 3, 2, 1, 90, 2, 255, 0, 0, 0, 255, 0])


def test_effect_speed_is_byte_offset_5():
    # APK_SECOND_PASS.md Q5(a): header [len, 0, 3, 2, style, speed, colorCount].
    payload = effect.build_show(4, [(1, 2, 3), (4, 5, 6)], speed=200)
    assert payload[:7] == bytearray([8, 0, 3, 2, 4, 200, 2])
    assert payload[7:] == bytearray([1, 2, 3, 4, 5, 6])


def test_effect_validation():
    two_colors = [(0, 0, 0), (255, 255, 255)]
    with pytest.raises(ValueError):
        effect.build_show(7, two_colors)
    with pytest.raises(ValueError):
        effect.build_show(0, two_colors[:1])
    with pytest.raises(ValueError):
        effect.build_show(0, two_colors, speed=256)
    with pytest.raises(ValueError):
        effect.build_show(0, two_colors, speed=-1)


def test_effect_chunked_single_packet_under_mtu():
    # 7 colors -> flat command is 7 + 21 = 28 bytes, one 96-byte-budget chunk:
    # sub-header [chunkLen + 1, chunkIndex] then the whole flat command.
    colors = [(i, i, i) for i in range(7)]
    flat = effect.build_show(2, colors)
    packets = effect.build_show_packets(2, colors)
    assert packets == [bytearray([len(flat) + 1, 0]) + flat]


def test_effect_chunked_18_byte_framing_reassembles_to_flat():
    colors = [(i, i, i) for i in range(7)]
    flat = effect.build_show(2, colors, speed=120)
    packets = effect.build_show_packets(2, colors, speed=120, mtu_negotiated=False)
    assert len(packets) == 2  # 28 payload bytes at <=18 per chunk
    assert packets[0][:2] == bytearray([18 + 1, 0])
    assert packets[1][:2] == bytearray([(len(flat) - 18) + 1, 1])
    assert packets[0][2:] + packets[1][2:] == flat


def test_music_sync():
    assert music_sync.build_set_mic_type(2) == bytearray([6, 0, 11, 128, 2, 100])
    assert music_sync.build_send_image_rhythm(5) == bytearray([6, 0, 0, 2, 5, 1])
    assert music_sync.build_stop_rhythm() == bytearray([6, 0, 0, 2, 0, 0])


def test_set_mic_type_matches_captured_frame():
    """GOLDEN CORRECTION 2026-07-25 (vendor-app HCI capture, decoded with
    pyidotmatrix/btsnoop.py): the app sends SIX bytes, [06 00 0b 80 01 64] --
    mic_type=1 with a trailing value=100. This builder previously emitted five
    bytes while its own length byte declared six.
    """
    assert music_sync.build_set_mic_type(1, 100) == bytearray([0x06, 0x00, 0x0B, 0x80, 0x01, 0x64])
    assert len(music_sync.build_set_mic_type(1)) == music_sync.build_set_mic_type(1)[0]


@pytest.mark.parametrize("value", [-1, 101, 255])
def test_set_mic_type_value_out_of_range_rejected(value):
    with pytest.raises(ValueError):
        music_sync.build_set_mic_type(1, value)


def test_rhythm_levels_matches_captured_frame():
    """Capture-exact 2026-07-25: a constant [21 00 01 02 00] prefix followed by
    16 level bytes. Byte 0 is 0x21 = 33, NOT the 21-byte frame length.
    """
    levels = [0x00, 0x03, 0x07, 0x0D, 0x0A, 0x05, 0x02, 0x01,
              0x01, 0x02, 0x05, 0x0A, 0x0D, 0x07, 0x03, 0x00]
    frame = music_sync.build_rhythm_levels(levels)
    assert frame == bytearray([0x21, 0x00, 0x01, 0x02, 0x00, *levels])
    assert len(frame) == 21
    assert frame[0] != len(frame)  # the prefix byte is not a length field


def test_rhythm_levels_accepts_the_apps_mirrored_palindrome():
    # The app mirrors 8 FFT bands into a 16-value palindrome; nothing on the
    # wire requires it, but the shape must build cleanly.
    bands = [0, 1, 2, 3, 4, 5, 6, 7]
    frame = music_sync.build_rhythm_levels([*bands, *reversed(bands)])
    assert list(frame[5:]) == [0, 1, 2, 3, 4, 5, 6, 7, 7, 6, 5, 4, 3, 2, 1, 0]


@pytest.mark.parametrize("levels", [[], [1] * 15, [1] * 17])
def test_rhythm_levels_rejects_wrong_length(levels):
    with pytest.raises(ValueError):
        music_sync.build_rhythm_levels(levels)


@pytest.mark.parametrize("bad", [-1, 256])
def test_rhythm_levels_rejects_out_of_range_level(bad):
    with pytest.raises(ValueError):
        music_sync.build_rhythm_levels([bad] + [0] * 15)


def test_common_time_and_flip():
    when = datetime(2026, 7, 11, 20, 30, 15)
    payload = common.build_set_time(when)
    assert payload[:8] == bytearray([11, 0, 1, 128, 26, 7, 11, when.weekday() + 1])
    assert payload[8:] == bytearray([20, 30, 15])
    assert common.build_set_screen_flipped(True) == bytearray([5, 0, 6, 128, 1])


def test_common_reset_is_packet_structure():
    assert common.build_reset() == [[bytearray.fromhex("04 00 03 80")]]
