"""SimulatorDisplay: an in-memory panel behind the DisplayBackend interface.

Holds an RGB framebuffer that show_frame replaces and set_pixels mutates, so the
daemon can run without hardware and the dashboard can preview frames. The
optional on_frame callback fires after every change with the current framebuffer.

emulate_timing reproduces the measured device costs (a full frame is far slower
than a pixel update), so pacing logic can be exercised without hardware.
"""

import asyncio
from collections.abc import Callable

from pyidotmatrix.display.backend import Color, ConnectionCallback, Coordinate, validate_coordinates
from pyidotmatrix.screen import ScreenSize
from pyidotmatrix.validation import validate_brightness

# Measured on hardware (see research lab): a full DIY frame is processed in
# ~1.5 s; a graffiti pixel command in ~0.02 s.
_FULL_FRAME_SECONDS = 1.5
_PIXEL_COMMAND_SECONDS = 0.02

FrameCallback = Callable[[bytes], None]


class SimulatorDisplay:
    def __init__(
        self,
        screen_size: ScreenSize,
        id: str = "simulator",
        emulate_timing: bool = False,
        on_frame: FrameCallback | None = None,
    ):
        self.id = id
        self.width = screen_size.width
        self.height = screen_size.height
        self._emulate_timing = emulate_timing
        self._on_frame = on_frame
        self._framebuffer = bytearray(screen_size.pixel_count * 3)
        self._connected = False
        self._brightness = 100
        self._powered = True
        self._on_connected: list[ConnectionCallback] = []
        self._on_disconnected: list[ConnectionCallback] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def brightness(self) -> int:
        """Last brightness set on the simulator (percent)."""
        return self._brightness

    @property
    def power(self) -> bool:
        """Whether the simulator is 'powered on'. Frames are still accepted and
        emitted while off — consumers decide how to render an off panel."""
        return self._powered

    @property
    def framebuffer(self) -> bytes:
        """A snapshot of the current pixels — useful for assertions and preview."""
        return bytes(self._framebuffer)

    async def connect(self) -> None:
        self._connected = True
        await self._notify(self._on_connected)

    async def disconnect(self) -> None:
        self._connected = False
        await self._notify(self._on_disconnected)

    async def show_frame(self, rgb: bytes, wait_for_device: bool = True) -> None:
        expected = self.width * self.height * 3
        if len(rgb) != expected:
            raise ValueError(f"frame must be {expected} bytes ({self.width}x{self.height} RGB), got {len(rgb)}")
        self._framebuffer[:] = rgb
        if self._emulate_timing and wait_for_device:
            await asyncio.sleep(_FULL_FRAME_SECONDS)
        self._emit_frame()

    async def set_pixels(self, color: Color, xys: list[Coordinate], wait_for_device: bool = False) -> None:
        validate_coordinates(xys, self.width, self.height)
        for x, y in xys:
            offset = (y * self.width + x) * 3
            self._framebuffer[offset:offset + 3] = bytes(color)
        if self._emulate_timing:
            await asyncio.sleep(_PIXEL_COMMAND_SECONDS)
        self._emit_frame()

    async def set_brightness(self, percent: int) -> None:
        validate_brightness(percent)
        self._brightness = percent

    async def set_power(self, on: bool) -> None:
        self._powered = on

    def add_listener(
        self,
        on_connected: ConnectionCallback | None = None,
        on_disconnected: ConnectionCallback | None = None,
    ) -> None:
        if on_connected:
            self._on_connected.append(on_connected)
        if on_disconnected:
            self._on_disconnected.append(on_disconnected)

    def _emit_frame(self) -> None:
        if self._on_frame:
            self._on_frame(self.framebuffer)

    async def _notify(self, callbacks: list[ConnectionCallback]) -> None:
        for callback in callbacks:
            await callback()
