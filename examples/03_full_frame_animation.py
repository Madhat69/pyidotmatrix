"""Renders a simple moving pattern as full DIY frames, paced to the panel's
actual render rate rather than flooding it.

What this shows:
    - building raw RGB frames by hand (width*height*3 bytes, row-major,
      top-left origin -- see docs/protocol-notes.md "Geometry")
    - client.display.show_frame() -- the full-frame path
    - why you pace full-frame sends at all

Hardware needed: one iDotMatrix panel.

    python examples/03_full_frame_animation.py AA:BB:CC:DD:EE:FF
"""

import asyncio
import sys

from pyidotmatrix import DeviceInfo, IDotMatrixClient, ScreenSize, discover

# HARDWARE-MEASURED (probes/probe_streaming_benchmark.py, 2026-07-20; see
# docs/protocol-notes.md "Streaming & performance"): the device RENDERS full
# DIY frames at a hard ~1.75 fps cap no matter how fast you send them -- an
# unacked flood just gets sampled-and-dropped. Sending faster than this wastes
# bandwidth and, per the same benchmark, sustained flooding twice dropped the
# BLE link outright. For real sustained animation, prefer graffiti/set_pixels
# deltas (see 04_graffiti_pixels.py); this example paces at the cap because
# full frames are the simplest way to show *some* motion, not the recommended
# animation path.
_DEVICE_RENDER_FPS = 1.75
_FRAME_INTERVAL_SECONDS = 1 / _DEVICE_RENDER_FPS

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


def build_moving_column_frame(size: int, column: int) -> bytes:
    """A width*height*3 RGB frame: a single white vertical column on black,
    at x=column. Row-major, top-left origin (display.show_frame's contract)."""
    row = bytearray(BLACK * size)
    lit_row = bytearray(row)
    lit_row[column * 3:column * 3 + 3] = WHITE
    return bytes(lit_row) * size


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
        size = screen_size.width
        print(f"sweeping a column left-to-right, one frame every {_FRAME_INTERVAL_SECONDS:.2f}s ...")
        for lap in range(2):
            for column in range(size):
                frame = build_moving_column_frame(size, column)
                # wait_for_device=True (the default) blocks until the device
                # acks the frame -- that ack doubles as flow control, so this
                # loop is naturally paced close to the render cap already.
                await client.display.show_frame(frame)
                await asyncio.sleep(max(0.0, _FRAME_INTERVAL_SECONDS))
            print(f"lap {lap + 1}/2 done")


if __name__ == "__main__":
    asyncio.run(main())
