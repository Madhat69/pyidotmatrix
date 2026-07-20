"""Transform discriminator v2: same 7 cases + attributed ack logging."""

import asyncio
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

CASES = [
    (1, 0, (255, 0, 0), "RED     b3=1 b4=0"),
    (1, 1, (0, 255, 0), "GREEN   b3=1 b4=1"),
    (1, 2, (0, 128, 255), "BLUE    b3=1 b4=2"),
    (1, 3, (255, 220, 0), "YELLOW  b3=1 b4=3"),
    (1, 4, (255, 0, 255), "MAGENTA b3=1 b4=4"),
    (2, 0, (255, 255, 255), "WHITE   b3=2 b4=0"),
    (4, 0, (0, 255, 255), "CYAN    b3=4 b4=0"),
]

t0 = time.perf_counter()


def stamp() -> str:
    return f"[{time.perf_counter() - t0:6.2f}s]"


def pixel(color, byte3, byte4):
    return bytearray([10, 0, 5, byte3, byte4, *color, 5, 5])


async def main() -> None:
    print(f"connecting to {ADDRESS} ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        client.add_response_listener(lambda ack: print(f"{stamp()}   ack: {ack!r}", flush=True))
        write = client.graffiti._send
        for n in range(5, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)
        for byte3, byte4, color, label in CASES:
            await write(bytearray([5, 0, 4, 1, 1]))
            await asyncio.sleep(0.8)
            print(f"{stamp()} SENDING {label}", flush=True)
            await write(pixel(color, byte3, byte4))
            await asyncio.sleep(5)
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
