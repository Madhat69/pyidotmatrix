"""Builders for basic device commands. Pure functions, no I/O.

Byte layouts reverse-engineered from the iDotMatrix app (BleProtocolN.java),
ported verbatim from the research lab.
"""

from datetime import datetime

from idotmatrix.validation import (
    validate_brightness,
    validate_byte,
    validate_password,
    validate_screen_timeout,
)

# 0xFF in the screen-timeout value byte requests a read-back instead of a write.
_SCREEN_TIMEOUT_READ_SENTINEL = 255


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


def build_verify_password(password: int) -> bytearray:
    """Authenticates against a password already set with build_set_password.

    Uses the same 6-digit-as-3-bytes encoding as build_set_password. Ack shape
    unconfirmed (likely the standard 5-byte fa03 accept/reject) — verify on
    hardware with a device that actually has a password set.
    """
    validate_password(password)
    high = (password // 10000) % 256
    mid = (password // 100) % 100 % 256
    low = password % 100 % 256
    return bytearray([7, 0, 5, 2, high, mid, low])


def build_set_screen_timeout(value: int) -> bytearray:
    """Sets the screen-on / auto-dim timer.

    Units are unknown pending a hardware test — seconds, minutes, and a
    preset-enum index are all plausible readings of the raw byte. Value must be
    0..254; 255 is reserved for build_read_screen_timeout.
    """
    validate_screen_timeout(value)
    return bytearray([5, 0, 15, 128, value])


def build_read_screen_timeout() -> bytearray:
    """Requests a read-back of the current screen timeout; reply expected on fa03."""
    return bytearray([5, 0, 15, 128, _SCREEN_TIMEOUT_READ_SENTINEL])


def build_set_time_indicator(enabled: bool) -> bytearray:
    """EXPERIMENTAL: toggles a time indicator on the clock face.

    Bytes are confirmed still shipped by the current (2026) official app, but the
    original research lab noted this command "doesn't seem to work" on some
    firmware/models. Unverified on GlanceOS hardware.
    """
    return bytearray([5, 0, 7, 128, 1 if enabled else 0])


def build_delete_device_data() -> bytearray:
    """EXPERIMENTAL and DESTRUCTIVE: erases device data ("Agreement" reset).

    Byte-identical across multiple app versions (a good stability signal), but
    never hardware-verified by this driver and irreversible on the device side.
    Callers must gate this behind an explicit confirmation — see
    IDotMatrixClient.experimental.delete_device_data.
    """
    return bytearray([17, 0, 2, 1, 12, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])


def build_reset() -> list[list[bytearray]]:
    """Reset the device internals. Returns packet structure (sent like a frame).

    Credit: 8none1 — https://github.com/8none1/idotmatrix
    """
    return [[bytearray.fromhex("04 00 03 80")]]
