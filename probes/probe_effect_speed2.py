"""Effect speed extremes: style 4, speed 1 vs 255, red-flash separator."""

import asyncio

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
COLORS = [(255, 0, 0), (255, 220, 0), (0, 128, 255)]


async def main() -> None:
    print(f"connecting to {ADDRESS} ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        for n in range(5, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)

        await client.effect.show(4, COLORS, speed=1)
        print("STEP A: style4 SPEED=1 (slowest possible) -- watch 10s", flush=True)
        await asyncio.sleep(10)

        await client.color.show((255, 0, 0))
        print("  (red flash = speed change marker)", flush=True)
        await asyncio.sleep(2)

        await client.effect.show(4, COLORS, speed=255)
        print("STEP B: style4 SPEED=255 (fastest possible) -- faster than A? (10s)", flush=True)
        await asyncio.sleep(10)

        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
