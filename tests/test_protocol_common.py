"""Tests for brightness and power command builders."""

import pytest

from idotmatrix.protocol import common


def test_brightness_payload():
    assert common.build_set_brightness(50) == bytearray([5, 0, 4, 128, 50])


@pytest.mark.parametrize("percent", [4, 0, 101, 255])
def test_brightness_out_of_range_rejected(percent):
    with pytest.raises(ValueError):
        common.build_set_brightness(percent)


def test_power_payload():
    assert common.build_set_power(True) == bytearray([5, 0, 7, 1, 1])
    assert common.build_set_power(False) == bytearray([5, 0, 7, 1, 0])
