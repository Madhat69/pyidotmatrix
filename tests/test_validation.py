"""Validation now raises on out-of-range input instead of silently wrapping."""

import pytest

from pyidotmatrix.protocol import clock, common, effect, fullscreen_color, graffiti, music_sync


@pytest.mark.parametrize("bad", [(256, 0, 0), (0, -1, 0), (0, 0, 999)])
def test_color_builders_reject_out_of_range(bad):
    with pytest.raises(ValueError):
        fullscreen_color.build_show_color(bad)
    with pytest.raises(ValueError):
        clock.build_show(0, color=bad)
    with pytest.raises(ValueError):
        graffiti.build_set_pixels(bad, [(0, 0)])


def test_effect_rejects_out_of_range_color():
    with pytest.raises(ValueError):
        effect.build_show(1, [(0, 0, 0), (300, 0, 0)])


def test_music_sync_rejects_out_of_range_byte():
    with pytest.raises(ValueError):
        music_sync.build_set_mic_type(500)


def test_valid_values_still_build():
    # Regression guard: in-range values are unaffected by the raise-not-wrap change.
    assert fullscreen_color.build_show_color((255, 128, 0))[4:] == bytearray([255, 128, 0])


@pytest.mark.parametrize("password", [-1, 1000000])
def test_verify_password_rejects_out_of_range(password):
    with pytest.raises(ValueError):
        common.build_verify_password(password)


@pytest.mark.parametrize("value", [-1, 255, 256])
def test_screen_timeout_rejects_out_of_range(value):
    with pytest.raises(ValueError):
        common.build_set_screen_timeout(value)
