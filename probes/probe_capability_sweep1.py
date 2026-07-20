"""Capability sweep batch 1: device control + native modes (operator-observed).

Targets (all SOURCE_DERIVED in capabilities.py as of 2026-07-20):
  common.set_screen_flipped   -- clock should render upside down, then back
  common.freeze_screen        -- freeze, then draw a graffiti row: does it appear?
  chronograph.set_mode        -- stopwatch start / pause
  countdown.set_mode          -- 30s countdown, stopped early
  scoreboard.show             -- 12 : 34

Also the first live dogfood of the SDK-M2 surface: connect_to() + async with +
reject-raises _send (any nack now raises CommandRejectedError).

Ends by restoring the native clock. No password, no destructive commands.
"""

import asyncio
from collections.abc import Awaitable, Callable

from pyidotmatrix import CommandRejectedError, IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import graffiti

ADDRESS = "6D:FD:F8:A0:3E:AF"


async def step(label: str, seconds: float) -> None:
    print(label)
    await asyncio.sleep(seconds)


async def guarded(label: str, call: Callable[[], Awaitable[None]]) -> None:
    """A device nack now raises CommandRejectedError (SDK-M2) -- for a probe
    that IS a finding, not a reason to abort the batch."""
    try:
        await call()
    except CommandRejectedError as ex:
        print(f"  !! {label} NACKED: {ex}")


async def main() -> None:
    print(f"connecting via SDK connect_to() to {ADDRESS} ...")
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        print("connected (context manager entered).")

        await guarded("flip on", lambda: client.common.set_screen_flipped(True))
        await step("1. FLIPPED=True  << is the clock upside down?", 5)
        await guarded("flip off", lambda: client.common.set_screen_flipped(False))
        await step("2. FLIPPED=False << back to normal?", 4)

        await guarded("freeze", client.common.freeze_screen)
        await step("3. FREEZE sent   << did anything visibly change?", 3)
        row = graffiti.build_set_pixels((255, 255, 255), [(x, 16) for x in range(8, 24)])
        await guarded("graffiti row", lambda: client.graffiti._send(row))
        await step("4. graffiti row sent while frozen << did a white row appear mid-screen?", 5)

        await guarded("chrono start", client.chronograph.start)
        await step("5. CHRONOGRAPH start << stopwatch counting on panel?", 7)
        await guarded("chrono pause", client.chronograph.pause)
        await step("6. CHRONOGRAPH pause << did it stop counting?", 4)

        await guarded("countdown start", lambda: client.countdown.start(0, 30))
        await step("7. COUNTDOWN 30s << counting down?", 8)
        await guarded("countdown stop", client.countdown.stop)
        await step("8. COUNTDOWN stop << countdown gone?", 3)

        await guarded("scoreboard", lambda: client.scoreboard.show(12, 34))
        await step("9. SCOREBOARD 12:34 << two scores shown?", 5)

        await guarded("clock restore", lambda: client.clock.show())
        print("10. clock restored. disconnecting via __aexit__.")
    print("done.")


if __name__ == "__main__":
    asyncio.run(main())
