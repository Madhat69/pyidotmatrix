"""BleDisplay: a real iDotMatrix panel behind the DisplayBackend interface.

Maps backend calls onto protocol builders and the BLE transport. It holds one
piece of device state — whether DIY draw mode is active — because a full frame
can only be shown in that mode, and entering it is a protocol requirement rather
than app policy.

Entering DIY mode is a protocol requirement, but *how* to enter it is not: the
device supports a clean entry (mode 1, ENTER_CLEAR_CUR_SHOW -- always takes,
black-flashes) and a flash-free one (mode 3, ENTER_NO_CLEAR_CUR_SHOW -- does
not reliably take over an EFFECT state, see protocol/image.py). Choosing
between them depends on the panel's history across the daemon's run, which
this driver has no visibility into -- so it stays opinion-free (Architect
ruling O-27, DAEMON_PLAN.md) and exposes `set_entry_clear` for the embedder
to drive. As of O-27's 2026-07-18 amendment the daemon always requests
clear=True (mode 3 was retired from daemon policy after a live probe showed
it doesn't reliably take on re-entry) -- this driver still supports both
modes unchanged; only the embedder's policy moved.
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
        # Default clear=True (mode 1): with no embedder telling us otherwise,
        # the panel's prior state is unknown, and mode 1 is the only entry
        # hardware-confirmed to always take. See set_entry_clear.
        self._entry_clear = True

        # A dropped connection loses device-side mode state; re-enter DIY on the
        # next frame after any reconnect. _entry_clear is deliberately NOT reset
        # here -- it reflects the embedder's policy (the daemon always requests
        # clear=True per O-27's 2026-07-18 amendment), not per-connection device
        # state, and persists until the embedder calls set_entry_clear again.
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

    def set_entry_clear(self, clear: bool) -> None:
        """Sets whether the *next* DIY-mode entry clears the panel.

        `clear=True` enters via mode 1 (ENTER_CLEAR_CUR_SHOW): always takes,
        black-flashes. `clear=False` enters via mode 3 (ENTER_NO_CLEAR_CUR_SHOW):
        flash-free, but hardware-confirmed to NOT reliably take over an EFFECT
        state -- see protocol/image.py's caveat.

        This driver holds no opinion on which is correct for a given moment --
        that is a function of the panel's history across the daemon's run
        (Architect ruling O-27, DAEMON_PLAN.md), which only the embedder
        tracks. As of O-27's 2026-07-18 amendment the daemon always calls
        this with clear=True -- a live probe found mode 3 does not reliably
        take once the device has left the daemon's DIY frame, which is true
        of every re-entry since every re-entry follows a disconnect. Mode 3
        remains supported here for callers that want it. Takes effect on the
        next entry only (i.e. the next show_frame call after a fresh
        connect/reconnect, when _diy_mode_enabled is False) -- it does nothing
        if DIY mode is already active this connection.
        """
        self._entry_clear = clear

    def invalidate_diy_mode(self) -> None:
        """Marks DIY mode as no-longer-active so the next show_frame re-enters.

        For embedders whose OTHER commands on the shared transport took the
        panel out of DIY without a disconnect -- native text/clock/effect
        modes. This object cannot see those commands (they go through feature
        namespaces, not this display), so the embedder must tell it.

        HARDWARE EVIDENCE (2026-07-20, 32x32): after a native-text takeover
        ended, the daemon's reclaim frame was silently swallowed -- this flag
        still said "in DIY" so no entry command was sent, and full frames into
        text mode are dropped (graffiti deltas painted through; only a later
        periodic keyframe healed the panel). Calling this before the reclaim
        forces the mode-1 entry, which is hardware-proven to take from any
        panel state.
        """
        self._diy_mode_enabled = False

    async def _ensure_diy_mode(self) -> None:
        if not self._diy_mode_enabled:
            mode = image.ENTER_CLEAR_CUR_SHOW if self._entry_clear else image.ENTER_NO_CLEAR_CUR_SHOW
            await self._transport.write(image.build_set_diy_mode(mode=mode), response=True)
            self._diy_mode_enabled = True

    async def _on_disconnected(self) -> None:
        self._diy_mode_enabled = False
