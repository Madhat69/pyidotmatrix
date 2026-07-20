"""DisplayBackend: the single interface every display implementation satisfies.

Hardware (BleDisplay) and simulator (SimulatorDisplay) are interchangeable
behind this protocol, so the daemon, tests, and preview all target one contract.

The interface is deliberately small: show a full frame, set some pixels, and
basic device control. Choosing *between* full frames and pixel updates is the
caller's policy, not the backend's — the backend just does what it is told.
"""

from collections.abc import Awaitable, Callable
from typing import Optional, Protocol, runtime_checkable

Color = tuple[int, int, int]
Coordinate = tuple[int, int]
ConnectionCallback = Callable[[], Awaitable[None]]


def validate_coordinates(xys: list[Coordinate], width: int, height: int) -> None:
    """Enforces the set_pixels contract: every coordinate on-screen.

    Both backends call this so hardware and simulator reject bad input identically
    (the simulator would otherwise corrupt its framebuffer; the device's reaction
    to off-screen coordinates is undefined).
    """
    for x, y in xys:
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"coordinate ({x}, {y}) outside {width}x{height} display")


@runtime_checkable
class DisplayBackend(Protocol):
    id: str
    width: int
    height: int

    @property
    def is_connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def show_frame(self, rgb: bytes, wait_for_device: bool = True) -> None:
        """Displays a full frame. rgb length must equal width * height * 3.

        wait_for_device=True blocks until the device acknowledges the frame; the
        device uses that ack as its "frame processed" signal, so it doubles as
        flow control.
        """
        ...

    async def set_pixels(
        self, color: Color, xys: list[Coordinate], wait_for_device: bool = False
    ) -> None:
        """Sets every coordinate in xys to color, over the current framebuffer."""
        ...

    async def set_brightness(self, percent: int) -> None: ...

    async def set_power(self, on: bool) -> None: ...

    def add_listener(
        self,
        on_connected: Optional[ConnectionCallback] = None,
        on_disconnected: Optional[ConnectionCallback] = None,
    ) -> None: ...
