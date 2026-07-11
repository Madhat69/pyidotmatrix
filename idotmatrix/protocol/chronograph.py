"""Chronograph (stopwatch, counts up) command builder. Pure function."""

# mode: 0 = reset, 1 = start from zero, 2 = pause, 3 = resume
MODE_RESET = 0
MODE_START = 1
MODE_PAUSE = 2
MODE_RESUME = 3


def build_set_mode(mode: int) -> bytearray:
    if mode not in range(4):
        raise ValueError(f"chronograph mode must be 0..3, got {mode}")
    return bytearray([5, 0, 9, 128, mode])
