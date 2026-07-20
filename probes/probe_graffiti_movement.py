"""byte4=3 OVERALL_MOVEMENT: does repeating it animate/shift the drawing?"""

import asyncio

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"


def block(color, origin, byte4):
    xys = [(origin[0] + dx, origin[1] + dy) for dy in range(4) for dx in range(4)]
    size = 8 + 2 * len(xys)
    p = bytearray([size % 256, size // 256, 5, 1, byte4, *color])
    for x, y in xys:
        p += bytes((x, y))
    return p


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        for n in range(5, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)
        await client.display.show_frame(bytes(32 * 32 * 3))
        await asyncio.sleep(2)
        print("PHASE 1: WHITE 4x4 block, byte4=3, sent ONCE -- static? (6s)", flush=True)
        await client.graffiti._send(block((255, 255, 255), (14, 14), 3))
        await asyncio.sleep(6)
        print("PHASE 2: same block re-sent with byte4=3 ten times, 0.5s apart"
              " -- does anything MOVE? (watch)", flush=True)
        for _ in range(10):
            await client.graffiti._send(block((255, 255, 255), (14, 14), 3))
            await asyncio.sleep(0.5)
        await asyncio.sleep(4)
        print("PHASE 3: byte4=3 blocks at MARCHING positions x=4,8,12,16,20"
              " -- trail or single moving block? (watch)", flush=True)
        for x in (4, 8, 12, 16, 20):
            await client.graffiti._send(block((0, 255, 255), (x, 24), 3))
            await asyncio.sleep(1)
        await asyncio.sleep(5)
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
