"""Scoreboard command builder. Pure function."""

import struct

MAX_SCORE = 999


def build_show(count1: int, count2: int) -> bytearray:
    """Show two scores. Each is clamped to 0..999 (device buffer limit)."""
    packed1 = struct.pack("!H", max(0, min(MAX_SCORE, count1)))  # big-endian
    packed2 = struct.pack("!H", max(0, min(MAX_SCORE, count2)))
    # Device expects each score little-endian: LSB then MSB.
    return bytearray([8, 0, 10, 128, packed1[1], packed1[0], packed2[1], packed2[0]])
