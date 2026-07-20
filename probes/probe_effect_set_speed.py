"""Does common.set_speed control EFFECT animation? (Its no-effect-on-TEXT
negative is recorded; the vendor app's effect screen has a working speed dial,
so effect speed control exists somewhere. Byte-5 of the effect command itself
is proven inert at extremes.)"""

import asyncio

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
COLORS = [(255, 0, 0), (255, 220, 0), (0, 128, 255)]


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        for n in range(5, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)
        await client.effect.show(4, COLORS)
        print("STEP 0: effect style4 running at its default pace -- watch (6s)", flush=True)
        await asyncio.sleep(6)

        await client.common.set_speed(5)
        print("STEP 1: set_speed(5) sent mid-effect -- did it SLOW DOWN? (8s)", flush=True)
        await asyncio.sleep(8)

        await client.common.set_speed(100)
        print("STEP 2: set_speed(100) sent -- did it SPEED UP? (8s)", flush=True)
        await asyncio.sleep(8)

        await client.common.set_speed(50)
        print("STEP 3: set_speed(50) -- middle pace? (6s)", flush=True)
        await asyncio.sleep(6)

        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
