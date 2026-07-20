"""Capability sweep batch 3: eco, time indicator, music rhythm, chunked effect."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from pyidotmatrix import CommandRejectedError, IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
COLORS = [(255, 0, 0), (255, 220, 0), (0, 128, 255)]


async def guarded(label: str, call: Callable[[], Awaitable[None]]) -> None:
    try:
        await call()
        print(f"  ({label}: accepted)", flush=True)
    except CommandRejectedError as ex:
        print(f"  !! {label} NACKED: {ex}", flush=True)


async def main() -> None:
    print(f"connecting to {ADDRESS} ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        for n in range(10, 0, -1):
            print(f"  starting in {n} ...", flush=True)
            await asyncio.sleep(1)

        await client.clock.show()
        print("clock base shown (4s)", flush=True)
        await asyncio.sleep(4)

        now = datetime.now()
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)
        await guarded("eco ON", lambda: client.eco.set_mode(
            True, start.hour, start.minute, end.hour, end.minute, eco_brightness=5))
        print("STEP 1a: ECO ON, window covers now, brightness 5 -- panel dimmed? (8s)", flush=True)
        await asyncio.sleep(8)
        await guarded("eco OFF", lambda: client.eco.set_mode(False))
        print("STEP 1b: ECO OFF -- brightness back? (6s)", flush=True)
        await asyncio.sleep(6)

        await guarded("indicator ON", lambda: client.experimental.set_time_indicator(True))
        print("STEP 2a: TIME INDICATOR ON -- anything new on the clock? (8s)", flush=True)
        await asyncio.sleep(8)
        await guarded("indicator OFF", lambda: client.experimental.set_time_indicator(False))
        print("STEP 2b: TIME INDICATOR OFF (6s)", flush=True)
        await asyncio.sleep(6)

        await guarded("mic type", lambda: client.music_sync.set_mic_type(1))
        print("STEP 3: RHYTHM -- dancing figure? values 10..250 over ~10s", flush=True)
        for value in (10, 80, 200, 30, 250, 120, 60, 250, 10, 180):
            await guarded(f"rhythm {value}", lambda v=value: client.music_sync.send_image_rhythm(v))
            await asyncio.sleep(1)
        await guarded("rhythm stop", client.music_sync.stop_rhythm)
        print("STEP 3 end: rhythm stopped (3s)", flush=True)
        await asyncio.sleep(3)

        await guarded("chunked effect (mtu=True)", lambda: client.effect.show_chunked(4, COLORS))
        print("STEP 4a: CHUNKED EFFECT mtu=True -- did the style4 effect appear? (8s)", flush=True)
        await asyncio.sleep(8)
        await guarded("chunked effect (mtu=False)", lambda: client.effect.show_chunked(4, COLORS, mtu_negotiated=False))
        print("STEP 4b: CHUNKED EFFECT mtu=False -- effect (still) showing? (8s)", flush=True)
        await asyncio.sleep(8)

        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
