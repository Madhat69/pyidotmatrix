"""Builders for basic device commands. Pure functions, no I/O.

Byte layouts reverse-engineered from the iDotMatrix app (BleProtocolN.java),
ported verbatim from the research lab.
"""

from datetime import datetime

from idotmatrix.validation import validate_brightness, validate_byte


def build_set_brightness(percent: int) -> bytearray:
    """Screen brightness. Percent must be 5..100."""
    validate_brightness(percent)
    return bytearray([5, 0, 4, 128, percent])


def build_set_power(on: bool) -> bytearray:
    """Turn the screen on or off."""
    return bytearray([5, 0, 7, 1, 1 if on else 0])


def build_set_screen_flipped(flipped: bool) -> bytearray:
    """Rotate the screen 180 degrees."""
    return bytearray([5, 0, 6, 128, 1 if flipped else 0])


def build_freeze_screen() -> bytearray:
    """Freeze or unfreeze the current screen contents."""
    return bytearray([4, 0, 3, 0])


def build_set_speed(speed: int) -> bytearray:
    """Set an unknown 'speed' value. Not referenced by the app; kept for parity."""
    validate_byte(speed, "speed")
    return bytearray([5, 0, 3, 1, speed])


def build_set_joint(mode: int) -> bytearray:
    """Set 'joint' mode. Purpose unknown; kept for parity."""
    validate_byte(mode, "mode")
    return bytearray([5, 0, 12, 128, mode])


def build_set_time(when: datetime) -> bytearray:
    """Set the device clock. Accurate to the second."""
    if not (1 <= when.month <= 12):
        raise ValueError("month must be 1..12")
    if not (1 <= when.day <= 31):
        raise ValueError("day must be 1..31")
    return bytearray(
        [
            11, 0, 1, 128,
            when.year % 100,
            when.month,
            when.day,
            when.weekday() + 1,
            when.hour,
            when.minute,
            when.second,
        ]
    )


def build_set_password(password: int) -> bytearray:
    """Set a 6-digit password (000000..999999). Reset the device to clear it."""
    high = (password // 10000) % 256
    mid = (password // 100) % 100 % 256
    low = password % 100 % 256
    return bytearray([8, 0, 4, 2, 1, high, mid, low])


def build_reset() -> list[list[bytearray]]:
    """Reset the device internals. Returns packet structure (sent like a frame).

    Credit: 8none1 — https://github.com/8none1/idotmatrix
    """
    return [[bytearray.fromhex("04 00 03 80")]]
