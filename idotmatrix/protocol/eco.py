"""Eco-mode command builder. Pure function.

Eco mode lowers brightness to a set level between a start and end time.
"""


def build_set_mode(
    enabled: bool,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
    eco_brightness: int,
) -> bytearray:
    if not (0 <= start_hour < 24) or not (0 <= end_hour < 24):
        raise ValueError("hours must be 0..23")
    if not (0 <= start_minute < 60) or not (0 <= end_minute < 60):
        raise ValueError("minutes must be 0..59")
    if not (0 <= eco_brightness < 256):
        raise ValueError("eco_brightness must be 0..255")
    return bytearray(
        [
            10, 0, 2, 128,
            1 if enabled else 0,
            start_hour % 256,
            start_minute % 256,
            end_hour % 256,
            end_minute % 256,
            eco_brightness % 256,
        ]
    )
