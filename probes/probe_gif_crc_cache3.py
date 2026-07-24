"""P2c -- instant GIF switching: does CHUNK 1 ALONE activate a stored GIF?

probe_gif_crc_cache2.py proved the device recognizes a stored GIF from the
first chunk's header CRC (per-chunk status 3 from ack #1 on a re-upload).
The engineering question: if the sender STOPS there, does the device actually
SWITCH PLAYBACK to the stored GIF? If yes, "show stored GIF" costs one chunk
(~1.3 s) instead of a full upload -- the instant-takeover primitive.

Phase 1: panel shows the clock; send ONLY chunk 1 of the seed-7 noise GIF
         (stored by the previous probe). Does noise playback start?
Phase 2 (doubles as PROBE_PLAN P10 case b): send ONLY chunk 1 of a NEVER
         uploaded GIF (seed 99), then abandon the transfer. Expect status 1
         (device waiting for chunk 2). Does the panel change? Does the
         abandoned transfer corrupt anything afterwards?
Phase 3: clock restore + a normal full upload of a third GIF (seed 100) to
         prove the device recovered cleanly from the abandoned transfer.

RESULT (2026-07-24): protocol behaviour clear; playback-switch UNANSWERED.
  1. PHASE 1: sent ONLY chunk 1 of the STORED seed-7 gif -> single ack status=3
     at +1.06s (device recognizes the stored payload from the header CRC).
  2. PHASE 2: sent ONLY chunk 1 of the UNKNOWN seed-99 gif, then abandoned ->
     single ack status=1 at +1.29s (device waits for chunk 2; doubles as
     PROBE_PLAN P10 case b -- first-chunk-abandon at the protocol level).
  3. PHASE 3 (recovery): clock, then a normal full upload of a seed-100 fixture
     -> textbook handshake, ten status=1 then terminal status=0 at +8.42s (this
     run DID capture the terminal). Operator confirmed it played normally.
  4. OPERATOR ANOMALY (unattributed -- operator was typing during PHASE 1 or 2
     and could not attribute which): the panel stuttered/lagged, showed
     CRT-like artifacts, and some bottom-row pixels turned orange-ish and
     FROZE. Transient: by phase 3 everything was normal and the clock restored
     cleanly.
  5. UNANSWERED: whether chunk 1 of the stored GIF actually SWITCHED PLAYBACK
     from clock to the noise animation (operator missed it). Superseded by the
     isolation probe probes/probe_gif_chunk1_isolation.py.
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
    """Identical generator to probe_gif_crc_cache2.py -- must stay in sync."""
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

        stored = gif.build_packets(make_big_gif(seed=7))     # stored on device
        unknown = gif.build_packets(make_big_gif(seed=99))   # never uploaded

        await client.clock.show()
        print("clock up as the baseline.", flush=True)

        await countdown("PHASE 1: chunk 1 ONLY of the STORED noise GIF -- does playback switch?")
        acks.clear()
        t0 = time.perf_counter()
        await client.gif._send_packets([stored[0]])
        print(f"chunk 1 sent ({time.perf_counter() - t0:.2f}s). Watch the panel. (10s)", flush=True)
        await asyncio.sleep(10)
        for ts, r in acks:
            print(f"  +{ts - t0:6.2f}s  {r}", flush=True)

        await countdown("PHASE 2: chunk 1 ONLY of an UNKNOWN GIF, then abandon -- panel change?")
        acks.clear()
        t0 = time.perf_counter()
        await client.gif._send_packets([unknown[0]])
        print(f"chunk 1 sent ({time.perf_counter() - t0:.2f}s), transfer now abandoned. (10s)", flush=True)
        await asyncio.sleep(10)
        for ts, r in acks:
            print(f"  +{ts - t0:6.2f}s  {r}", flush=True)

        await countdown("PHASE 3: recovery -- clock, then a fresh full upload (seed 100)")
        await client.clock.show()
        await asyncio.sleep(3)
        acks.clear()
        t0 = time.perf_counter()
        await client.gif.upload_bytes(make_big_gif(seed=100))
        print(f"full upload after abandon: {time.perf_counter() - t0:.2f}s -- did it play normally? (8s)", flush=True)
        await asyncio.sleep(8)
        for ts, r in acks:
            print(f"  +{ts - t0:6.2f}s  {r}", flush=True)

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
