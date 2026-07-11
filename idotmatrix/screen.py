"""Supported display sizes."""

from enum import Enum


class ScreenSize(Enum):
    """Square display sizes, as (width, height) in pixels."""

    SIZE_16x16 = (16, 16)
    SIZE_32x32 = (32, 32)
    SIZE_64x64 = (64, 64)

    @property
    def width(self) -> int:
        return self.value[0]

    @property
    def height(self) -> int:
        return self.value[1]

    @property
    def pixel_count(self) -> int:
        return self.width * self.height
