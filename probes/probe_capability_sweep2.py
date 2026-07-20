"""Capability sweep batch 2: flip, chronograph retry, effect speed A/B,
freeze-during-animation (operator-observed, generous pacing).

Batch 1 (probe_capability_sweep1.py, 2026-07-20) verified countdown,
scoreboard, and clock restore; found graffiti draws land DURING freeze; and
chronograph.start showed nothing visible -- retried here with a long window.
Freeze gets an observable test this time: freeze while an effect animates.
"""

import asyncio
from collections.abc import Awaitable, Callable

from pyidotmatrix import CommandRejectedError, IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

COLORS = [(255, 0, 0), (0, 255, 0), (0, 128, 255)]


async def step(label: str, seconds: float) -> None:
    print(label, flush=True)
    await asyncio.sleep(seconds)


async def guarded(label: str, call: Callable[[], Awaitable[None]]) -> None:
    try:
        await call()
    except CommandRejectedError as ex:
        print(f"  !! {label} NACKED: {ex}", flush=True)


async def main() -> None:
    print(f"connecting to {ADDRESS} ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        for n in range(10, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)

        await guarded("flip on", lambda: client.common.set_screen_flipped(True))
        await step("STEP 1a: FLIP ON -- clock upside down? (8s)", 8)
        await guarded("flip off", lambda: client.common.set_screen_flipped(False))
        await step("STEP 1b: FLIP OFF -- back to normal? (8s)", 8)

        await guarded("chrono start", client.chronograph.start)
        await step("STEP 2: CHRONOGRAPH START -- watch 10s: anything at all?", 10)
        await guarded("clock restore", lambda: client.clock.show())
        await step("   (clock restored, 4s breather)", 4)

        await guarded("effect slow", lambda: client.effect.show(0, COLORS, speed=10))
        await step("STEP 3a: EFFECT style0 SPEED=10 -- how fast is it moving? (8s)", 8)
        await guarded("effect fast", lambda: client.effect.show(0, COLORS, speed=200))
        await step("STEP 3b: EFFECT style0 SPEED=200 -- visibly faster? (8s)", 8)

        await guarded("freeze", client.common.freeze_screen)
        await step("STEP 4a: FREEZE sent mid-animation -- did the effect STOP moving? (8s)", 8)
        await guarded("freeze again", client.common.freeze_screen)
        await step("STEP 4b: FREEZE sent AGAIN -- did it resume (toggle)? (8s)", 8)

        await guarded("clock restore", lambda: client.clock.show())
        print("STEP 5: clock restored. done.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
