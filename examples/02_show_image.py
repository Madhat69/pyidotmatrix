"""Adapts a still image to the 32x32 canvas and displays it as one full frame.

What this shows:
    - client.show_image() -- the one-line convenience (adapt + show_frame)
    - the lower-level pieces it wraps (adapt_image + display.show_frame),
      for callers who want to inspect or cache the adapted bytes

Hardware needed: one iDotMatrix panel. Pass its address and an image path:

    python examples/02_show_image.py AA:BB:CC:DD:EE:FF photo.png
    python examples/02_show_image.py "" photo.png   # empty address -> discover()
"""

import asyncio
import sys

from pyidotmatrix import (
    DeviceInfo,
    IDotMatrixClient,
    ResizeMode,
    ScreenSize,
    adapt_image,
    discover,
)


async def resolve_device(arg: str) -> DeviceInfo | str:
    """A non-empty argv[1] is used as-is; an empty string falls back to
    discovery (see 01_discover_and_clock.py for the discovery path itself)."""
    if arg:
        return arg
    devices = await discover()
    if not devices:
        raise SystemExit("No iDotMatrix panel found and no address given.")
    return devices[0]


async def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(f"usage: python {sys.argv[0]} <address-or-empty> <image-path>")
    device = await resolve_device(sys.argv[1])
    image_path = sys.argv[2]

    async with IDotMatrixClient.connect_to(device, ScreenSize.SIZE_32x32) as client:
        # The one-liner: fits the image to the panel (letterboxed by default)
        # and pushes it as a full framebuffer frame.
        print(f"showing {image_path} via client.show_image() ...")
        await client.show_image(image_path, resize_mode=ResizeMode.FIT)
        await asyncio.sleep(3)

        # Same result, spelled out -- useful if you want to adapt once and
        # reuse the bytes (e.g. cache them, or diff against the next frame)
        # rather than re-adapting on every show_image() call.
        print("same image again, via adapt_image() + display.show_frame() ...")
        rgb_bytes = adapt_image(
            image_path,
            canvas_size=client.screen_size.width,
            resize_mode=ResizeMode.FILL,       # this time: crop to fill, no letterbox
            background_color=(0, 0, 0),
        )
        # rgb_bytes is exactly width*height*3 bytes -- show_frame enforces that.
        await client.display.show_frame(rgb_bytes)
        await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
