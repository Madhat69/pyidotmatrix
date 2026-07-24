"""P2b -- does the GIF CRC dedup answer arrive EARLY on a multi-chunk re-upload?

probe_gif_crc_cache.py proved the device recognizes byte-identical GIF payloads
(terminal status 3 vs 0) but at 2 chunks there was nothing to skip. Here: a
noise GIF ~10x that size, uploaded cold then re-uploaded. Our sender is blind
(fires every chunk regardless), so the ack TIMELINE tells the story:

  - If the re-upload's terminal 3 lands only after the last chunk, dedup is a
    storage detail -- no speed win possible.
  - If a 3 shows up early (near chunk 1's timestamp, while we are still
    sending), the device decides from the header CRC -- and a smarter sender
    could stop right there: near-instant GIF switching for GlanceOS takeovers.

Operator: noise animation plays twice; note whether the re-upload visibly
restarts it or leaves it running.

RESULT (2026-07-24): dedup answer arrives EARLY -- early-exit is viable.
  Fixture: 44845 bytes ~ 11 outer chunks of 4096 (seed-7 noise, 32 frames).
  1. UPLOAD 1 (cold): 9.77s wall; 10 captured acks, ALL status=1 (NEXT_CHUNK)
     at ~0.7-1.1s cadence (+1.00 through +8.94). The terminal ack landed after
     our last write returned and was missed by the capture window -- a probe
     artifact, not a device omission.
  2. UPLOAD 2 (byte-identical re-upload): 8.65s wall; 9 captured acks -- status=3
     from the VERY FIRST ack (+1.34s) and for every chunk except one anomalous
     status=0 at +6.49s (single occurrence, unexplained -- recorded as an
     anomaly, not theorized). Terminal acks again missed post-return.
  3. CONCLUSION: the device recognizes a stored GIF from the FIRST chunk's
     header CRC. A sender that stopped on the first status=3 would cut this
     re-upload from ~8.7s to ~1.3s -- the instant-takeover prize. Whether
     chunk 1 alone SWITCHES PLAYBACK is the next probe's question
     (probes/probe_gif_chunk1_isolation.py).
"""

import asyncio
import io
import math
import random
import time

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
CHUNK = 4096


def make_big_gif(seed: int) -> bytes:
    """Deterministic 32-frame noise GIF -- LZW-hostile so it stays large."""
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


async def countdown(label: str, n: int = 5) -> None:
    print(f"\n=== {label} in {n}s ===", flush=True)
    for i in range(n, 0, -1):
        print(f"  {i} ...", flush=True)
        await asyncio.sleep(1)


async def main() -> None:
    acks: list[tuple[float, str]] = []
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        unsubscribe = client.add_response_listener(lambda a: acks.append((time.perf_counter(), repr(a))))
        gif_big = make_big_gif(seed=7)
        chunks = math.ceil(len(gif_big) / CHUNK)
        print(f"fixture: {len(gif_big)} bytes ~ {chunks} outer chunks", flush=True)

        for label in ("UPLOAD 1: cold", "UPLOAD 2: byte-identical re-upload"):
            await countdown(label)
            acks.clear()
            t0 = time.perf_counter()
            await client.gif.upload_bytes(gif_big)
            dt = time.perf_counter() - t0
            print(f"{label}: {dt:.2f}s wall, {len(acks)} acks:", flush=True)
            for ts, r in acks:
                print(f"  +{ts - t0:6.2f}s  {r}", flush=True)
            await asyncio.sleep(6)

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
