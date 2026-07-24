"""P2e -- make the GIF silent-failure model VISIBLE with distinguishable fixtures.

probe_gif_stored_chunk1.py established status model v2 from ack traces alone:
GIF speaks Timer/Schedule's vocabulary (1 = NEXT_CHUNK, 3 = SAVED, 0 = FAILED),
and a mid-stream status=0 silently dooms the whole transfer (later chunks still
ack 1, but no terminal 3 lands and nothing is saved). That was inferred, not
seen -- every fixture so far was identical-looking noise, so the operator could
never tell a doomed upload from a saved one on the panel.

This probe removes that blind spot. Each fixture is confined to ONE visible
color -- RED, GREEN, BLUE, YELLOW -- so the panel itself reports the outcome:
if an upload's trace shows a mid-stream 0 / missing terminal 3, the PREVIOUS
color should still be playing (a silent failure you can SEE); if it ends 3, the
new color should take over.

Hypothesis: upload terminals correlate 1:1 with what's on the panel -- terminal
3 => the new color plays; a mid-stream 0 with no terminal 3 => the prior color
keeps playing (silent failure), reproducing the ~1-in-4 rate visually.

Baseline: clock (10s health).
Four cold full uploads in order RED(201), GREEN(202), BLUE(203), YELLOW(204):
    10s countdown announcing the expected color; 3s ack-tail before the trace;
    terminal summary; 10s "which color is playing NOW?" watch.
Summary: per-color terminal distribution.
Cleanup: clock.

RESULT (2026-07-__): pending.
"""

import asyncio
import io
import random
import time

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

_CHANNEL_TINT = {
    "red": lambda v: (v, 0, 0),
    "green": lambda v: (0, v, 0),
    "blue": lambda v: (0, 0, v),
    "yellow": lambda v: (v, v, 0),
}


def make_tinted_gif(channel: str, seed: int) -> bytes:
    """Same 32-frame / 32x32 / 300-px noise shape as probe_gif_stored_chunk1.py's
    make_big_gif, but every lit pixel is confined to ONE channel so the fixture
    is unmistakably RED, GREEN, BLUE, or YELLOW to the naked eye (yellow = the
    red+green pair). Distinguishable fixtures are the whole point -- a silently
    doomed upload leaves the PREVIOUS color on the panel."""
    tint = _CHANNEL_TINT[channel]
    rng = random.Random(seed)
    frames = []
    for _ in range(32):
        im = Image.new("RGB", (32, 32), (0, 0, 0))
        px = im.load()
        for _ in range(300):
            px[rng.randrange(32), rng.randrange(32)] = tint(rng.randrange(64, 256))
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

        await client.clock.show()
        await countdown("BASELINE: clock up -- panel healthy? no leftovers?")

        # RED first, then GREEN/BLUE/YELLOW: after each upload the panel color is
        # the visual ground truth against the ack terminal.
        terminals: list[tuple[str, str]] = []
        for color, seed in (("red", 201), ("green", 202), ("blue", 203), ("yellow", 204)):
            await countdown(f"COLD UPLOAD: {color.upper()} noise (seed {seed}) -- EXPECT {color.upper()} next")
            acks.clear()
            t0 = time.perf_counter()
            await client.gif.upload_bytes(make_tinted_gif(color, seed=seed))
            print(f"{color} full upload: {time.perf_counter() - t0:.2f}s.", flush=True)
            await asyncio.sleep(3)  # ack-tail: capture the terminal before we print
            trace = list(acks)
            for ts, r in trace:
                print(f"  +{ts - t0:6.2f}s  {r}", flush=True)
            terminal = trace[-1][1] if trace else "<none>"
            terminals.append((color, terminal))
            print(f"{color} terminal status: {terminal}.", flush=True)
            print(f"  WATCH (10s): which color is playing NOW? EXPECT {color.upper()} if this ended 3;", flush=True)
            print("             the PREVIOUS color if the trace shows a mid-stream 0 / no terminal 3", flush=True)
            print("             (that is the silent failure, made visible).", flush=True)
            await asyncio.sleep(10)

        print("\n=== per-color terminal distribution ===", flush=True)
        print("  " + "  |  ".join(f"{c}: {t}" for c, t in terminals), flush=True)

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
