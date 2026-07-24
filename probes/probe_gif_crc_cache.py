"""P2 -- GIF CRC cache (PROBE_PLAN.md; idotmatrix-overclocked's claim).

Claim: the device caches GIFs by CRC32 -- re-uploading identical bytes returns
SAVED immediately with no NEXT_CHUNK round trips. Design: three timed uploads
(cold A / byte-identical A repeat / cold B control) with a full attributed ack
trace. If t2 collapses versus t1 AND t3, the cache is real; if t2 ~= t3, there
is no cache and upload time is just proportional to payload size.

Operator: the panel plays a random-pixel GIF each phase; note whether upload 2
visibly restarts/flickers the animation or leaves it running untouched.

RESULT (2026-07-24): TWO findings, one of them about our own code.
  1. SDK bug caught live: (1,0) was missing from _STATUS_ACK_KEYS, so GIF
     status frames misparsed as boolean DeviceAcks and logged spurious
     "device rejected type=1 subtype=0" on every successful upload -- the
     fourth victim of the misparse class (timer, schedule, text before it).
     Fixed same day in protocol/response.py.
  2. CRC dedup is real: terminal status 3 on the byte-identical re-upload vs
     terminal 0 on both cold uploads (fresh store; the GIF PLAYED, so 0 is
     SUCCESS in this family, unlike Timer/Schedule where 0 = FAILED).
     t1=1.12s t2=1.07s t3=1.05s -- no wall-time benefit at 2 chunks; whether
     SAVED arrives early enough to skip chunks on a big re-upload (the real
     prize) is probe_gif_crc_cache2.py's question.
"""

import asyncio
import io
import random
import time

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"


def make_gif(seed: int) -> bytes:
    """Deterministic 8-frame 32x32 random-pixel GIF; seed controls the bytes."""
    rng = random.Random(seed)
    frames = []
    for _ in range(8):
        im = Image.new("RGB", (32, 32), (0, 0, 0))
        px = im.load()
        for _ in range(80):
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


async def timed_upload(client: IDotMatrixClient, gif: bytes, label: str, acks: list) -> float:
    before = len(acks)
    t0 = time.perf_counter()
    await client.gif.upload_bytes(gif)
    dt = time.perf_counter() - t0
    print(f"{label}: {dt:.2f}s wall, {len(acks) - before} acks", flush=True)
    return dt


async def main() -> None:
    acks: list[tuple[float, str]] = []
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        unsubscribe = client.add_response_listener(lambda a: acks.append((time.perf_counter(), repr(a))))
        gif_a = make_gif(seed=42)
        gif_b = make_gif(seed=43)
        print(f"fixture A: {len(gif_a)} bytes / fixture B: {len(gif_b)} bytes", flush=True)

        await countdown("UPLOAD 1: fixture A, cold")
        t1 = await timed_upload(client, gif_a, "upload 1 (A cold)", acks)
        await asyncio.sleep(5)

        await countdown("UPLOAD 2: fixture A again, byte-identical")
        t2 = await timed_upload(client, gif_a, "upload 2 (A repeat)", acks)
        await asyncio.sleep(5)

        await countdown("UPLOAD 3: fixture B, different bytes (control)")
        t3 = await timed_upload(client, gif_b, "upload 3 (B cold)", acks)
        await asyncio.sleep(5)

        print("\nack trace:", flush=True)
        base = acks[0][0] if acks else 0.0
        for ts, r in acks:
            print(f"  +{ts - base:7.2f}s  {r}", flush=True)

        cache_signal = t2 < t1 * 0.5 and t2 < t3 * 0.5
        print(
            f"\nt1={t1:.2f}s  t2={t2:.2f}s  t3={t3:.2f}s  ->  "
            f"{'CACHE SIGNAL: repeat collapsed' if cache_signal else 'no cache signal (t2 ~= cold uploads)'}",
            flush=True,
        )

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
