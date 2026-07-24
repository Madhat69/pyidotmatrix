"""Drives SimulatorDisplay -- the in-memory DisplayBackend -- and prints each
frame as ASCII art. No hardware needed at all.

What this shows:
    - SimulatorDisplay satisfies the same DisplayBackend interface as
      BleDisplay (show_frame, set_pixels, brightness, power), so code written
      against it ports to real hardware unchanged
    - the on_frame callback for observing every change as it happens

Hardware needed: none. Just run it:

    python examples/07_simulator.py
"""

import asyncio

from pyidotmatrix import ScreenSize, SimulatorDisplay

# Small canvas so the ASCII rendering stays readable in a terminal.
_SCREEN_SIZE = ScreenSize.SIZE_16x16

# Coarse ASCII buckets by brightness, darkest to brightest.
_RAMP = " .:-=+*#%@"


def frame_to_ascii(rgb: bytes, width: int, height: int) -> str:
    """Renders an RGB framebuffer as a grid of characters, one per pixel,
    picked by luminance -- good enough to eyeball shapes and motion."""
    lines = []
    for y in range(height):
        row_chars = []
        for x in range(width):
            offset = (y * width + x) * 3
            r, g, b = rgb[offset], rgb[offset + 1], rgb[offset + 2]
            luminance = (r + g + b) / 3
            bucket = int(luminance / 256 * len(_RAMP))
            row_chars.append(_RAMP[min(bucket, len(_RAMP) - 1)])
        lines.append("".join(row_chars))
    return "\n".join(lines)


def on_frame(rgb: bytes) -> None:
    """SimulatorDisplay calls this after every show_frame/set_pixels change."""
    print(frame_to_ascii(rgb, _SCREEN_SIZE.width, _SCREEN_SIZE.height))
    print("-" * _SCREEN_SIZE.width)


async def main() -> None:
    display = SimulatorDisplay(_SCREEN_SIZE, on_frame=on_frame)
    await display.connect()

    # A full frame: a red-to-blue gradient across the width, same on every row.
    print("show_frame(): a horizontal gradient")
    width, height = _SCREEN_SIZE.width, _SCREEN_SIZE.height
    row = bytearray()
    for x in range(width):
        red = int(255 * (1 - x / (width - 1)))
        blue = 255 - red
        row += bytes((red, 0, blue))
    gradient = bytes(row) * height
    await display.show_frame(gradient)

    # A partial update: light up a plus-sign in the middle, over the gradient.
    print("\nset_pixels(): a plus-sign overlay")
    mid_x, mid_y = width // 2, height // 2
    cross = [(mid_x, y) for y in range(height)] + [(x, mid_y) for x in range(width)]
    await display.set_pixels((255, 255, 255), cross)

    # The framebuffer property is a synchronous snapshot -- handy for
    # assertions in tests, or a preview UI that polls rather than subscribes.
    print(f"\nframebuffer is {len(display.framebuffer)} bytes "
          f"({width}x{height}x3 = {width * height * 3})")

    await display.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
