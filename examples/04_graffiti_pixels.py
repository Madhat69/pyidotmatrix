"""Draws with delta pixel updates (graffiti) and demonstrates the h/v mirror
move_type -- the cheap path for small per-frame changes, unlike full frames.

What this shows:
    - client.graffiti.set_pixels() -- partial pixel updates over the current
      framebuffer (does NOT clear it first)
    - move_type=MOVE_HORIZONTAL_MIRROR / MOVE_VERTICAL_MIRROR: draws the given
      pixels PLUS a mirrored copy across the panel's center axis
      (hardware-mapped 2026-07-21, see pyidotmatrix/protocol/graffiti.py)

Note: graffiti writes are genuinely ack-silent on the wire -- the client never
opens a pending ack wait for them regardless of verify_commands, so there is
no CommandRejectedError path to handle here.

Hardware needed: one iDotMatrix panel.

    python examples/04_graffiti_pixels.py AA:BB:CC:DD:EE:FF
"""

import asyncio
import sys

from pyidotmatrix import DeviceInfo, IDotMatrixClient, ScreenSize, discover
from pyidotmatrix.protocol import graffiti

GREEN = (0, 255, 0)
CYAN = (0, 255, 255)


async def resolve_device() -> DeviceInfo | str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    devices = await discover()
    if not devices:
        raise SystemExit("No iDotMatrix panel found and no address given.")
    return devices[0]


async def main() -> None:
    device = await resolve_device()
    screen_size = ScreenSize.SIZE_32x32

    async with IDotMatrixClient.connect_to(device, screen_size) as client:
        # Clear the canvas with one full frame so the graffiti deltas below
        # have a clean black background to draw over.
        black_frame = bytes(screen_size.pixel_count * 3)
        await client.display.show_frame(black_frame)
        await asyncio.sleep(1)

        # Plain delta draw: a short diagonal line near the top-left corner.
        # No clearing -- these pixels land on top of whatever is already shown.
        diagonal = [(x, x) for x in range(4, 10)]
        print("drawing a plain diagonal (move_type=MOVE_NONE) ...")
        await client.graffiti.set_pixels(GREEN, diagonal, move_type=graffiti.MOVE_NONE)
        await asyncio.sleep(2)

        # Horizontal mirror: draws `diagonal` again PLUS a mirrored copy
        # across the panel's vertical center line -- you'll see a second
        # diagonal appear on the right half without sending its coordinates.
        print("drawing another diagonal with move_type=MOVE_HORIZONTAL_MIRROR ...")
        mirrored_diagonal = [(x, x + 12) for x in range(4, 10)]
        await client.graffiti.set_pixels(
            CYAN, mirrored_diagonal, move_type=graffiti.MOVE_HORIZONTAL_MIRROR
        )
        await asyncio.sleep(2)

        # Vertical mirror: same idea, mirrored across the horizontal center line.
        print("drawing a third shape with move_type=MOVE_VERTICAL_MIRROR ...")
        low_shape = [(x, 26) for x in range(10, 16)]
        await client.graffiti.set_pixels(
            GREEN, low_shape, move_type=graffiti.MOVE_VERTICAL_MIRROR
        )
        await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
