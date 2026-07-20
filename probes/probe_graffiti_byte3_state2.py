"""byte3 discriminator v2: 3x3 blocks instead of invisible single pixels."""

import asyncio
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

t0 = time.perf_counter()

CASES = [
    (0, (255, 0, 0), (3, 8), "RED    b3=0 left"),
    (2, (0, 255, 0), (11, 8), "GREEN  b3=2 mid-left"),
    (3, (0, 128, 255), (19, 8), "BLUE   b3=3 mid-right"),
    (4, (255, 220, 0), (27, 8), "YELLOW b3=4 right"),
]


def block(color, origin, byte3):
    xys = [(origin[0] + dx, origin[1] + dy) for dy in range(3) for dx in range(3)]
    size = 8 + 2 * len(xys)
    p = bytearray([size % 256, size // 256, 5, byte3, 0, *color])
    for x, y in xys:
        p += bytes((x, y))
    return p


async def main() -> None:
    print(f"connecting to {ADDRESS} ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        client.add_response_listener(
            lambda ack: print(f"[{time.perf_counter() - t0:6.2f}s]   ack: {ack!r}", flush=True)
        )
        for n in range(5, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)
        print("black frame first ...", flush=True)
        await client.display.show_frame(bytes(32 * 32 * 3))
        await asyncio.sleep(2)
        for byte3, color, origin, label in CASES:
            print(f"[{time.perf_counter() - t0:6.2f}s] SENDING {label}", flush=True)
            await client.graffiti._send(block(color, origin, byte3))
            await asyncio.sleep(4)
        print("<< four 3x3 blocks in a row: which colors exist? (12s)", flush=True)
        await asyncio.sleep(12)
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
