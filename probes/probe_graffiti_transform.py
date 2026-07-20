"""Graffiti transform-field discriminator: single off-center pixel per case.

The byte4=2 "two-back recolor" theory is DEAD: a single pixel at (15,28) with
byte4=2 drew TWO dots -- (15,28) and its VERTICAL MIRROR (15,3). Every earlier
"recolor" observation is exactly explained by vertical mirroring onto the
symmetric probe layout. byte4 is the real transform field.

This run: one pixel at (5,5) per case, screen cleared between cases, distinct
colors. A second dot to the RIGHT (26,5) = horizontal mirror; BELOW (5,26) =
vertical; DIAGONAL (26,26) = both. Also re-tests byte3 values with an
off-center pixel, since the 2026-07-12 byte3 sweep used mirror-blind layouts.
"""

import asyncio

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

CASES = [
    (1, 0, (255, 0, 0), "RED     b3=1 b4=0 (baseline: expect ONE dot)"),
    (1, 1, (0, 255, 0), "GREEN   b3=1 b4=1"),
    (1, 2, (0, 128, 255), "BLUE    b3=1 b4=2 (expect TWO: below = vertical)"),
    (1, 3, (255, 220, 0), "YELLOW  b3=1 b4=3"),
    (1, 4, (255, 0, 255), "MAGENTA b3=1 b4=4"),
    (2, 0, (255, 255, 255), "WHITE   b3=2 b4=0"),
    (4, 0, (0, 255, 255), "CYAN    b3=4 b4=0"),
]


def pixel(color, byte3, byte4):
    return bytearray([10, 0, 5, byte3, byte4, *color, 5, 5])


async def main() -> None:
    print(f"connecting to {ADDRESS} ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        write = client.graffiti._send
        for n in range(5, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)
        for byte3, byte4, color, label in CASES:
            await write(bytearray([5, 0, 4, 1, 1]))  # clear via DIY mode 1
            await asyncio.sleep(0.8)
            await write(pixel(color, byte3, byte4))
            print(f"{label} -- dots: how many, where? (5s)", flush=True)
            await asyncio.sleep(5)
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
