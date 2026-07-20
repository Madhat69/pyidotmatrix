"""Validation for public parameters.

The SDK raises on out-of-range input rather than silently wrapping it (the old
`% 256` behavior). A caller passing 300 for a color channel has a bug; surfacing
it beats painting the wrong color on a panel across the room.

Depends on nothing else in the package, so any module may import it.
"""

MIN_BRIGHTNESS_PERCENT = 5
MAX_BRIGHTNESS_PERCENT = 100

MIN_PASSWORD = 0
MAX_PASSWORD = 999999

MIN_SCREEN_TIMEOUT = 0
MAX_SCREEN_TIMEOUT = 254  # 255 is reserved as the read-back sentinel


def validate_rgb(color: tuple[int, int, int]) -> None:
    if len(color) != 3 or not all(isinstance(c, int) and 0 <= c <= 255 for c in color):
        raise ValueError(f"color must be three ints 0..255, got {color!r}")


def validate_byte(value: int, name: str = "value") -> None:
    if not (isinstance(value, int) and 0 <= value <= 255):
        raise ValueError(f"{name} must be an int 0..255, got {value!r}")


def validate_brightness(percent: int) -> None:
    if not (MIN_BRIGHTNESS_PERCENT <= percent <= MAX_BRIGHTNESS_PERCENT):
        raise ValueError(
            f"brightness must be {MIN_BRIGHTNESS_PERCENT}..{MAX_BRIGHTNESS_PERCENT}, got {percent}"
        )


def validate_password(password: int) -> None:
    if not (isinstance(password, int) and MIN_PASSWORD <= password <= MAX_PASSWORD):
        raise ValueError(f"password must be an int {MIN_PASSWORD}..{MAX_PASSWORD}, got {password!r}")


def validate_screen_timeout(value: int) -> None:
    if not (isinstance(value, int) and MIN_SCREEN_TIMEOUT <= value <= MAX_SCREEN_TIMEOUT):
        raise ValueError(
            f"screen timeout must be an int {MIN_SCREEN_TIMEOUT}..{MAX_SCREEN_TIMEOUT} "
            f"(255 is reserved for build_read_screen_timeout), got {value!r}"
        )
