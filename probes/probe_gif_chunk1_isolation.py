"""P2d -- disambiguation: does a single chunk 1 SWITCH PLAYBACK or GLITCH?

probe_gif_crc_cache3.py left two things fused together: a stored GIF's chunk 1
returns status=3 (recognized), and SOMEWHERE in that session the panel showed a
transient glitch (stutter/lag, CRT-like artifacts, bottom-row pixels stuck
orange-ish) that the operator could not attribute to a phase. This probe pulls
the two apart with deliberate, isolated single-chunk sends and health-check
windows between every step, so any glitch can be pinned to the send that caused
it -- and so we finally learn whether chunk 1 ALONE flips playback.

Hypothesis: chunk 1 of a STORED gif switches the panel to that GIF (instant
takeover primitive); chunk 1 of an UNKNOWN gif does not (device waits for more).
Either send may or may not be the source of the earlier render glitch.

Baseline: clock, 10s health check.
PHASE B: chunk 1 ONLY of the STORED seed-7 gif; 15s observation.
Recovery: clock, 10s health check.
PHASE C: chunk 1 ONLY of a NEVER-uploaded gif (seed 101 -- NOT 99, which is
         contaminated by cache3's abandoned half-transfer); 15s observation.
Recovery: clock, 10s health check.
FINAL: full upload of a seed-102 fixture to prove clean recovery; 8s watch.

RESULT (2026-07-__): pending.
"""

import asyncio
import io
import random
import time

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import gif

ADDRESS = "6D:FD:F8:A0:3E:AF"


def make_big_gif(seed: int) -> bytes:
    """Identical generator to probe_gif_crc_cache3.py -- must stay byte-identical/in sync."""
    rng = random.Random(seed)
    frames = []
    for _ in range(32):
        im = Image.new("RGB", (32, 32), (0, 0, 0))
        px = im.load()
        for _ in range(300):
            px[rng.randrange(32), rng.randrange(32)] = (
                rng.randrange(256),
                rng.randrange(256),
                rng.randrange(256),
            )
        frames.append(im)
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=150, loop=0)
    return buf.getvalue()


async def countdown(label: str, n: int = 10) -> None:
    print(f"\n=== {label} in {n}s ===", flush=True)
    for i in range(n, 0, -1):
        print(f"  {i} ...", flush=True)
        await asyncio.sleep(1)


async def main() -> None:
    acks: list[tuple[float, str]] = []
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        unsubscribe = client.add_response_listener(lambda a: acks.append((time.perf_counter(), repr(a))))

        stored = gif.build_packets(make_big_gif(seed=7))     # stored on device (cache2/cache3)
        unknown = gif.build_packets(make_big_gif(seed=101))   # never uploaded, uncontaminated

        await client.clock.show()
        await countdown("BASELINE: clock up -- panel healthy? artifacts gone from last session?")

        await countdown("PHASE B: chunk 1 ONLY of the STORED seed-7 gif")
        acks.clear()
        t0 = time.perf_counter()
        await client.gif._send_packets([stored[0]])
        print(f"stored chunk 1 sent ({time.perf_counter() - t0:.2f}s). (15s)", flush=True)
        print("  WATCH-FOR: (a) does playback SWITCH from clock to noise?", flush=True)
        print("             (b) any stutter/artifacts/stuck pixels?", flush=True)
        await asyncio.sleep(15)
        for ts, r in acks:
            print(f"  +{ts - t0:6.2f}s  {r}", flush=True)

        await client.clock.show()
        await countdown("RECOVERY: clock back -- healthy again? did phase B leave anything stuck?")

        await countdown("PHASE C: chunk 1 ONLY of a NEVER-uploaded gif (seed 101)")
        acks.clear()
        t0 = time.perf_counter()
        await client.gif._send_packets([unknown[0]])
        print(f"unknown chunk 1 sent ({time.perf_counter() - t0:.2f}s). (15s)", flush=True)
        print("  WATCH-FOR: (a) does playback SWITCH from clock to noise?", flush=True)
        print("             (b) any stutter/artifacts/stuck pixels?", flush=True)
        await asyncio.sleep(15)
        for ts, r in acks:
            print(f"  +{ts - t0:6.2f}s  {r}", flush=True)

        await client.clock.show()
        await countdown("RECOVERY: clock back -- healthy again? did phase C leave anything stuck?")

        await countdown("FINAL: full upload of a seed-102 fixture -- clean recovery?")
        acks.clear()
        t0 = time.perf_counter()
        await client.gif.upload_bytes(make_big_gif(seed=102))
        print(f"full upload: {time.perf_counter() - t0:.2f}s -- did it play normally? (8s)", flush=True)
        await asyncio.sleep(8)
        for ts, r in acks:
            print(f"  +{ts - t0:6.2f}s  {r}", flush=True)

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
