"""P2d -- does the RECOGNIZED chunk 1 switch playback/glitch, and is terminal status stable?

probe_gif_chunk1_isolation.py cornered two loose ends. First, single-slot
recognition means only the CURRENTLY stored GIF's chunk 1 returns status=3 --
and that recognized-chunk-1 case is now the prime (one-sample) suspect for the
transient render glitch, because both UNrecognized lone-chunk cases reproduced
clean. Second, the "terminal 0 = fresh store, 3 = duplicate" mapping fell apart:
two near-identical cold uploads ended terminal 0 and terminal 3 respectively, so
we have no reliable terminal-status semantics.

This probe closes both. PHASE 1 fires ONLY chunk 1 of the currently stored
seed-102 gif and watches hard for a playback switch and/or glitch. PHASE 2 does
three consecutive cold full uploads (seeds 103/104/105) to sample the terminal
status distribution over fresh stores.

Hypothesis: chunk 1 of the stored gif returns status=3 (recognition) and is the
glitch source (playback-switch attempt); fresh full uploads do NOT terminate on
a single stable status -- terminal 0 vs 3 is not the fresh/duplicate signal it
looked like.

PHASE 1: clock baseline (10s health), then chunk 1 ONLY of the stored seed-102
         gif; 15s watch; 3s ack-tail before printing acks.
Recovery: clock, 10s health.
PHASE 2: cold full uploads of seeds 103, 104, 105 -- each with a 3s ack-tail
         before its trace, an 8s "did it play?" watch, and a terminal summary;
         then a distribution summary of the three terminals.
Cleanup: clock.

RESULT (2026-07-25, reference 32x32 panel, operator-narrated):

PHASE 1 (chunk 1 only of the currently stored seed-102 gif, clock showing): a
single ack status=3 at +1.10s, and the panel VISIBLY SWITCHED from clock to the
noise animation -- no artifacts, no stutter. INSTANT PLAYBACK SWITCH CONFIRMED:
one recognized chunk (~1s) is enough to activate the currently stored gif. The
prior day's transient render glitch did NOT reproduce in its exact trigger
condition -- downgrade it to an unexplained one-off (kept on record, not a
finding).

PHASE 2 (three cold full uploads, ~44.8KB / 11 chunks each, 3s ack tails):
  - seed 103: ten status=1, terminal status=3 at +8.22s.
  - seed 104: status=1, then status=0 at +2.00s (chunk-2 position), then nine
    more status=1, and NO terminal 3 EVER.
  - seed 105: ten status=1, terminal status=3 at +8.75s.
  Operator: playback "got stuck in the middle and resumed"; the phases were
  indistinguishable because all fixtures are identical-looking noise (design
  flaw -- P2e uses per-channel tinted fixtures to fix this).

REVISED STATUS MODEL (v2) -- supersedes the v1 comments committed 2026-07-24.
For GIF (0x01, 0x00) the vocabulary matches Timer/Schedule after all:
  1 = chunk accepted, send the next;
  3 = SAVED (terminal success; ALSO sent from chunk 1 onward when re-uploading
      the CURRENTLY stored gif -- single-slot CRC recognition, which also
      switches playback per phase 1);
  0 = chunk REJECTED and the transfer is doomed -- the device keeps acking 1 for
      later chunks but never emits a terminal 3, and nothing is saved.
Reinterpreting past data under v2: the 2026-07-24 small-fixture uploads that
"ended 0" were SILENT FAILURES (the operator couldn't tell -- every fixture was
identical noise and the previously stored gif kept playing). Observed
silent-failure rate across sessions ~1 in 4, so our blind GIF sender (no status
handling) is genuinely unreliable -- a status-aware upload is a pending SDK work
item.
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
    """Identical generator to probe_gif_chunk1_isolation.py -- must stay byte-identical/in sync."""
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

        stored = gif.build_packets(make_big_gif(seed=102))  # currently stored on device (from isolation probe FINAL)

        await client.clock.show()
        await countdown("BASELINE: clock up -- panel healthy? no leftovers?")

        # --- PHASE 1: the headline test -- recognized chunk 1 alone ---
        await countdown("PHASE 1: chunk 1 ONLY of the STORED seed-102 gif")
        acks.clear()
        t0 = time.perf_counter()
        await client.gif._send_packets([stored[0]])
        print(f"stored chunk 1 sent ({time.perf_counter() - t0:.2f}s). (15s)", flush=True)
        print("  WATCH-FOR: (a) EXPECT ack status=3 -- recognition of the stored gif.", flush=True)
        print("             (b) does playback SWITCH from clock to noise?", flush=True)
        print("             (c) any stutter/CRT artifacts/stuck pixels? (prime glitch suspect)", flush=True)
        await asyncio.sleep(15)
        await asyncio.sleep(3)  # ack-tail: terminals landed post-return in earlier runs
        for ts, r in acks:
            print(f"  +{ts - t0:6.2f}s  {r}", flush=True)

        await client.clock.show()
        await countdown("RECOVERY: clock back -- healthy again? did phase 1 leave anything stuck?")

        # --- PHASE 2: terminal-status distribution over fresh stores ---
        terminals: list[tuple[int, str]] = []
        for seed in (103, 104, 105):
            await countdown(f"PHASE 2: cold full upload of seed-{seed}")
            acks.clear()
            t0 = time.perf_counter()
            await client.gif.upload_bytes(make_big_gif(seed=seed))
            print(f"seed {seed} full upload: {time.perf_counter() - t0:.2f}s.", flush=True)
            await asyncio.sleep(3)  # ack-tail: capture the terminal before we print
            trace = list(acks)
            for ts, r in trace:
                print(f"  +{ts - t0:6.2f}s  {r}", flush=True)
            terminal = trace[-1][1] if trace else "<none>"
            terminals.append((seed, terminal))
            print(f"seed {seed} terminal status: {terminal}. did it play? (8s)", flush=True)
            await asyncio.sleep(8)

        print("\n=== PHASE 2 terminal distribution ===", flush=True)
        print("  " + "  |  ".join(f"seed {s}: {t}" for s, t in terminals), flush=True)

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
