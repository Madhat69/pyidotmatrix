"""byte3 state-dependence discriminator: replicate the 2026-07-12 setup (full
black frame pushed first, graffiti onto an established framebuffer), then four
single pixels with byte3 = 0/2/3/4 at distinct positions. Conflicting priors:
07-12 said 3 nacks and 0/2/4 draw; tonight (fresh DIY-clear, no frame) 2
nacked and 4 was silently swallowed."""

import asyncio
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

t0 = time.perf_counter()

CASES = [
    (0, (255, 0, 0), (4, 4), "RED    b3=0 at x=4"),
    (2, (0, 255, 0), (12, 4), "GREEN  b3=2 at x=12"),
    (3, (0, 128, 255), (20, 4), "BLUE   b3=3 at x=20"),
    (4, (255, 220, 0), (27, 4), "YELLOW b3=4 at x=27"),
]


def pixel(color, xy, byte3):
    return bytearray([10, 0, 5, byte3, 0, *color, *xy])


async def main() -> None:
    print(f"connecting to {ADDRESS} ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        client.add_response_listener(
            lambda ack: print(f"[{time.perf_counter() - t0:6.2f}s]   ack: {ack!r}", flush=True)
        )
        for n in range(5, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)
        print("pushing full black frame (old-probe setup) ...", flush=True)
        await client.display.show_frame(bytes(32 * 32 * 3))
        await asyncio.sleep(2)
        for byte3, color, xy, label in CASES:
            print(f"[{time.perf_counter() - t0:6.2f}s] SENDING {label}", flush=True)
            await client.graffiti._send(pixel(color, xy, byte3))
            await asyncio.sleep(4)
        print("<< which dots exist along the top row: red? green? blue? yellow? (10s)", flush=True)
        await asyncio.sleep(10)
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
