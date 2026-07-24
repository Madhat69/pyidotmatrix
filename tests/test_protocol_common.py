"""Tests for brightness and power command builders."""

from datetime import UTC, datetime, timedelta, timezone

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


def test_set_password_payload():
    # Same 3-byte encoding as build_verify_password (shared _encode_password).
    assert common.build_set_password(123456) == bytearray([8, 0, 4, 2, 1, 12, 34, 56])
    assert common.build_set_password(0) == bytearray([8, 0, 4, 2, 1, 0, 0, 0])


@pytest.mark.parametrize("password", [-1, 1000000, 5000000])
def test_set_password_out_of_range_rejected(password):
    # Code review item 1: build_set_password previously skipped validation
    # entirely, so a negative/oversized value would encode garbage bytes
    # instead of raising -- must now validate identically to verify_password.
    with pytest.raises(ValueError):
        common.build_set_password(password)


def test_set_time_naive_input_unchanged():
    # Naive datetimes are assumed already device-local wall time -- no tz
    # conversion happens (item 5, code review).
    when = datetime(2026, 3, 5, 9, 15, 42)
    payload = common.build_set_time(when)
    assert payload[:8] == bytearray([11, 0, 1, 128, 26, 3, 5, when.weekday() + 1])
    assert payload[8:] == bytearray([9, 15, 42])


def test_set_time_tz_aware_converts_via_astimezone():
    # build_set_time must run tz-aware input through .astimezone() (device-local
    # wall time) before encoding -- verify against the exact same conversion
    # the implementation is documented to perform, so this test doesn't depend
    # on the host machine's local timezone.
    when = datetime(2026, 7, 11, 20, 30, 15, tzinfo=timezone(timedelta(hours=5)))
    expected_local = when.astimezone()
    payload = common.build_set_time(when)
    assert payload[:8] == bytearray(
        [11, 0, 1, 128, expected_local.year % 100, expected_local.month, expected_local.day,
         expected_local.weekday() + 1]
    )
    assert payload[8:] == bytearray([expected_local.hour, expected_local.minute, expected_local.second])


def test_set_time_tz_aware_same_instant_different_offsets_match():
    # Two tz-aware datetimes naming the same instant through different UTC
    # offsets must produce byte-identical output once both are normalized to
    # device-local wall time -- a host-timezone-independent correctness check.
    utc_time = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)
    plus5_time = utc_time.astimezone(timezone(timedelta(hours=5)))
    assert common.build_set_time(utc_time) == common.build_set_time(plus5_time)


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
