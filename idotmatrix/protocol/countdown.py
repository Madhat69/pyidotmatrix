"""Countdown (timer, counts down) command builder. Pure function.

A Pomodoro timer is a countdown: set minutes/seconds and start. Once started the
device runs and renders it autonomously, independent of the host.
"""

# mode: 0 = disable, 1 = start, 2 = pause, 3 = restart
MODE_DISABLE = 0
MODE_START = 1
MODE_PAUSE = 2
MODE_RESTART = 3


def build_set_mode(mode: int, minutes: int, seconds: int) -> bytearray:
    if mode not in range(4):
        raise ValueError(f"countdown mode must be 0..3, got {mode}")
    if not (0 <= minutes <= 59):
        raise ValueError(f"minutes must be 0..59, got {minutes}")
    if not (0 <= seconds <= 59):
        raise ValueError(f"seconds must be 0..59, got {seconds}")
    return bytearray([7, 0, 8, 128, mode % 256, minutes % 256, seconds % 256])
