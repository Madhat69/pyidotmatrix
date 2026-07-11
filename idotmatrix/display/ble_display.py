"""BleDisplay: a real iDotMatrix panel behind the DisplayBackend interface.

Maps backend calls onto protocol builders and the BLE transport. It holds one
piece of device state — whether DIY draw mode is active — because a full frame
can only be shown in that mode, and entering it is a protocol requirement rather
than app policy.
"""

import logging
from typing import Optional

from idotmatrix.display.backend import Color, ConnectionCallback, Coordinate, validate_coordinates
from idotmatrix.protocol import common, graffiti, image
from idotmatrix.screen import ScreenSize
from idotmatrix.transport.ble import BleTransport

logger = logging.getLogger(__name__)


class BleDisplay:
    def __init__(self, screen_size: ScreenSize, transport: BleTransport, id: str = "ble"):
        self.id = id
        self.width = screen_size.width
        self.height = screen_size.height
        self._transport = transport
        self._diy_mode_enabled = False

        # A dropped connection loses device-side mode state; re-enter DIY on the
        # next frame after any reconnect.
        transport.add_listener(on_disconnected=self._on_disconnected)

    @property
    def is_connected(self) -> bool:
        return self._transport.is_connected

    async def connect(self) -> None:
        await self._transport.connect()

    async def disconnect(self) -> None:
        await self._transport.disconnect()

    async def show_frame(self, rgb: bytes, wait_for_device: bool = True) -> None:
        expected = self.width * self.height * 3
        if len(rgb) != expected:
            raise ValueError(f"frame must be {expected} bytes ({self.width}x{self.height} RGB), got {len(rgb)}")
        await self._ensure_diy_mode()
        await self._transport.write_packets(image.build_frame_packets(rgb), response=wait_for_device)

    async def set_pixels(self, color: Color, xys: list[Coordinate], wait_for_device: bool = False) -> None:
        validate_coordinates(xys, self.width, self.height)
        # Split into device-sized batches; the protocol builder caps one command.
        for start in range(0, len(xys), graffiti.MAX_PIXELS_PER_COMMAND):
            batch = xys[start:start + graffiti.MAX_PIXELS_PER_COMMAND]
            await self._transport.write(graffiti.build_set_pixels(color, batch), response=wait_for_device)

    async def set_brightness(self, percent: int) -> None:
        await self._transport.write(common.build_set_brightness(percent), response=True)

    async def set_power(self, on: bool) -> None:
        await self._transport.write(common.build_set_power(on), response=True)

    def add_listener(
        self,
        on_connected: Optional[ConnectionCallback] = None,
        on_disconnected: Optional[ConnectionCallback] = None,
    ) -> None:
        self._transport.add_listener(on_connected, on_disconnected)

    async def _ensure_diy_mode(self) -> None:
        if not self._diy_mode_enabled:
            await self._transport.write(image.build_set_diy_mode(True), response=True)
            self._diy_mode_enabled = True

    async def _on_disconnected(self) -> None:
        self._diy_mode_enabled = False
