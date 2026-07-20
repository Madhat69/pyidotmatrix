"""Tests for brightness and power command builders."""

import pytest

from pyidotmatrix.protocol import common


def test_brightness_payload():
    assert common.build_set_brightness(50) == bytearray([5, 0, 4, 128, 50])


@pytest.mark.parametrize("percent", [4, 0, 101, 255])
def test_brightness_out_of_range_rejected(percent):
    with pytest.raises(ValueError):
        common.build_set_brightness(percent)


def test_power_payload():
    assert common.build_set_power(True) == bytearray([5, 0, 7, 1, 1])
    assert common.build_set_power(False) == bytearray([5, 0, 7, 1, 0])


def test_verify_password_payload():
    assert common.build_verify_password(123456) == bytearray([7, 0, 5, 2, 12, 34, 56])
    assert common.build_verify_password(0) == bytearray([7, 0, 5, 2, 0, 0, 0])


@pytest.mark.parametrize("password", [-1, 1000000, 5000000])
def test_verify_password_out_of_range_rejected(password):
    with pytest.raises(ValueError):
        common.build_verify_password(password)


def test_set_screen_timeout_payload():
    assert common.build_set_screen_timeout(30) == bytearray([5, 0, 15, 128, 30])
    assert common.build_set_screen_timeout(0) == bytearray([5, 0, 15, 128, 0])
    assert common.build_set_screen_timeout(254) == bytearray([5, 0, 15, 128, 254])


@pytest.mark.parametrize("value", [255, -1, 300])
def test_set_screen_timeout_out_of_range_rejected(value):
    with pytest.raises(ValueError):
        common.build_set_screen_timeout(value)


def test_read_screen_timeout_payload():
    assert common.build_read_screen_timeout() == bytearray([5, 0, 15, 128, 255])


def test_set_time_indicator_payload():
    assert common.build_set_time_indicator(True) == bytearray([5, 0, 7, 128, 1])
    assert common.build_set_time_indicator(False) == bytearray([5, 0, 7, 128, 0])


def test_delete_device_data_payload():
    assert common.build_delete_device_data() == bytearray(
        [17, 0, 2, 1, 12, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    )
