"""Effect speed A/B rerun: style 2, slow/fast/slow (operator-observed)."""

import asyncio

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
COLORS = [(255, 0, 0), (255, 220, 0), (0, 128, 255)]


async def main() -> None:
    print(f"connecting to {ADDRESS} ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        for n in range(10, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)

        await client.effect.show(2, COLORS, speed=10)
        print("STEP A: style2 SPEED=10  -- watch the motion (8s)", flush=True)
        await asyncio.sleep(8)

        await client.effect.show(2, COLORS, speed=200)
        print("STEP B: style2 SPEED=200 -- faster than A? (8s)", flush=True)
        await asyncio.sleep(8)

        await client.effect.show(2, COLORS, speed=10)
        print("STEP C: back to SPEED=10 -- slowed down again? (8s)", flush=True)
        await asyncio.sleep(8)

        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
