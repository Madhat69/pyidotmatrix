"""Chronograph clean-state retest: batch-2's run was contaminated by a paused
countdown from batch 1 (chrono.start appeared to RESUME the countdown). This
run starts from a clean clock with no timer state pending."""

import asyncio

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        for n in range(5, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)
        await client.chronograph.start()
        print("CHRONO START from clean state -- what appeared? counting UP? (10s)", flush=True)
        await asyncio.sleep(10)
        await client.chronograph.pause()
        print("CHRONO PAUSE -- did it stop? (5s)", flush=True)
        await asyncio.sleep(5)
        await client.chronograph.start()
        print("CHRONO START again -- resumed counting? (5s)", flush=True)
        await asyncio.sleep(5)
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
