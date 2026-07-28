"""P19 G7 -- a properly isolated dwell trial, with the decoy actually PERSISTED.

WHY THIS PROBE EXISTS
---------------------
The 2026-07-28 dwell ladder (probe_p19_g5_kill_event.py `own-delayed`) produced
a contradiction: 60 s died early in the session and SURVIVED later, same dwell,
same nominal setup. The device was not being arbitrary -- the protocol was
broken, twice, in the same way.

To ask "did this write survive the reconnect?" the panel must show something
DIFFERENT when the write is lost. That means the PERSISTED state has to differ
from what is being written. Two runs failed that:

  * the first "survivals" wrote ORANGE while orange was already persisted, so
    reversion and survival were the same picture;
  * the 60 s rerun activated a noise GIF to act as the decoy, but activating it
    only made it the ACTIVE mode -- it had ~10 s, nowhere near long enough to
    COMMIT -- while flash still held orange from the previous trial. Same
    picture again.

So a valid trial costs more than a dwell: the decoy must first be given a full
commit period of its own. That is what this probe does, and it is why it takes
minutes rather than seconds.

THE PROTOCOL
------------
  1. Activate the stored noise GIF and hold it PERSIST_SECONDS (default 200 s,
     comfortably past the ~180 s upper bound the ladder established), so the
     decoy is genuinely committed to flash rather than merely on screen.
  2. Disconnect / reconnect, and CONFIRM the panel still shows noise. This
     verifies the decoy persisted instead of assuming it -- if the panel shows
     anything else here, the run is void and says so.
  3. Write GREEN and hold it for the trial dwell (default 10 s).
  4. Disconnect / reconnect. GREEN means the write survived; NOISE means it was
     lost and the panel reverted to the committed decoy.

WHAT STEP 2 ALSO TESTS, deliberately
------------------------------------
That reconnect is itself "condition (B)" -- a prior disconnect/reconnect in the
same session, which twice rescued an 8-second-old GIF write in P11. So green is
written into a session that has already reconnected once, and the result reads
on both questions at once:

  GREEN survives at 10 s -> condition (B) is real and extends to fullscreen
                            colour, now shown with a properly persisted decoy.
  GREEN dies at 10 s     -> (B) does not extend to colour, and the ladder's low
                            end is re-anchored on a trial that is actually valid.

Green, not orange, purely so the operator can tell this run's content apart from
every previous one at a glance.

SAFETY
------
Activates an already-stored GIF, writes one fullscreen colour, and restores the
clock. No reset, no brightness, no eco, no flip, no RTC write, no graffiti, no
experimental namespace, nothing near the password or UART surface.

USAGE
-----
    python probes/probe_p19_g7_isolated_dwell.py trial [dwell_seconds]

The sequence argument is mandatory; dwell defaults to 10 s (5..300).
Runtime ~ PERSIST_SECONDS + dwell + 45 s, so ~4.5 min at the defaults.

RESULT (2026-07-28, dwell 10 s): **condition (B) CONFIRMED for fullscreen
colour, and activate_stored does NOT commit the gif it activates.**

Operator: `noise -> reconnect -> ORANGE -> green -> reconnect -> GREEN -> clock`.

1. WATCH #1 showed **ORANGE, not noise.** The decoy had been the ACTIVE display
   for a full 200 s -- longer than the 180 s that committed orange in the g5
   ladder -- and flash STILL held orange from that earlier trial. So
   `gif.activate_stored()` switches playback WITHOUT arming whatever the commit
   path is. Mechanism OPEN; recorded as observed, not explained. This is what
   the operator spotted: the P2 gif was live in RAM and never in flash, which
   only became visible when a power cycle booted the panel straight to orange.

2. WATCH #2 showed **GREEN -- the 10-second-old write SURVIVED.**

THE RUN IS NOT VOID DESPITE (1), and this is the point worth keeping: green
differs from BOTH candidate revert targets. A lost write would have shown orange
(flash) or noise (active); neither appeared. So WATCH #2 reads cleanly whichever
would have won -- the discriminator survived the premise failing.

WHAT IT SETTLES. A 10 s dwell died SIX times in the g5 ladder (8/30/60/75/90/100,
all first-connection sessions). The only thing this run had that those lacked is
step 2's reconnect, which happens BEFORE the write. That is condition (B) -- "a
prior disconnect/reconnect earlier in the same session makes subsequent writes
durable" -- previously demonstrated only for GIF uploads (`--preamble ble gif`,
twice) and now shown for fullscreen colour under a discriminator that cannot be
fooled by the flash state.

So the settled model is two INDEPENDENT sufficient conditions:
  (A) DWELL, no prior reconnect: threshold between 100 s and 180 s (g5 ladder;
      matches the 2026-07-12 "under ~3 min" record).
  (B) A PRIOR RECONNECT in the session: ~10 s is enough.

GlanceOS's double-tap connect puts every daemon session permanently in (B).

WHY THIS PROBE EXISTS AT ALL -- the protocol rule it encodes: to ask "did this
write survive?", the PERSISTED state must differ from what is being written, not
merely the ACTIVE one. Two earlier trials (`own-delayed 140` and the `own-delayed
60` rerun) are RETRACTED for exactly that: both wrote orange while orange was
already in flash, so reversion and survival were the same picture. Making a decoy
visible is not the same as making it committed, and committing costs a full dwell
period -- which is why a valid isolated trial takes ~6 minutes rather than 2.
"""

import asyncio
import io
import random
import sys

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

GIF_SEED = 215  # the noise fixture already stored on the device by P2b
GREEN = (0, 150, 80)  # calm, and unmistakably not the orange of every prior run

PERSIST_SECONDS = 200.0  # past the ~180 s upper bound, so the decoy really commits
DEFAULT_DWELL = 10.0
DWELL_MIN, DWELL_MAX = 5.0, 300.0
BLE_GAP_SECONDS = 6.0
WATCH_SECONDS = 10.0
SETTLE_SECONDS = 2.0

SEQUENCES = {"trial": "persist a noise decoy, verify it, then one dwell trial with GREEN"}


def print_usage() -> None:
    print("usage: python probes/probe_p19_g7_isolated_dwell.py trial [dwell_seconds]", flush=True)
    print("", flush=True)
    print("Runs exactly ONE sequence. The sequence argument is mandatory.", flush=True)
    print(f"dwell defaults to {DEFAULT_DWELL:.0f}s, range {DWELL_MIN:.0f}..{DWELL_MAX:.0f}.", flush=True)


def select(argv: list[str]) -> tuple[str, float]:
    """Validated before any BLE contact, so a typo cannot burn a panel session."""
    if not argv:
        print("error: a sequence name is required.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    if argv[0] not in SEQUENCES:
        print(f"error: unrecognized sequence {argv[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    rest = argv[1:]
    if not rest:
        return argv[0], DEFAULT_DWELL
    if len(rest) > 1:
        print(f"error: expected at most one dwell value, got {len(rest)}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    try:
        dwell = float(rest[0])
    except ValueError:
        print(f"error: dwell must be a number of seconds, got {rest[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2) from None
    if not DWELL_MIN <= dwell <= DWELL_MAX:
        print(f"error: dwell must be {DWELL_MIN:.0f}..{DWELL_MAX:.0f}s, got {dwell:g}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    return argv[0], dwell


def make_big_gif(seed: int) -> bytes:
    """Byte-identical to the P2/P2b generator -- a different one means a different CRC."""
    rng = random.Random(seed)
    frames = []
    for _ in range(32):
        im = Image.new("RGB", (32, 32), (0, 0, 0))
        px = im.load()
        for _ in range(300):
            px[rng.randrange(32), rng.randrange(32)] = (
                rng.randrange(256), rng.randrange(256), rng.randrange(256),
            )
        frames.append(im)
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=150, loop=0)
    return buf.getvalue()


def print_visual_script(dwell: float) -> None:
    total = (PERSIST_SECONDS + dwell + 45) / 60
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER ============================================", flush=True)
    print(f"  Total ~{total:.1f} min. Only TWO moments need your eyes; both are announced.", flush=True)
    print(f"  1. NOISE ({PERSIST_SECONDS:.0f}s): the speckle animation, held so it COMMITS to", flush=True)
    print("     flash. Nothing to judge -- this is setup, and the long wait IS the fix", flush=True)
    print("     for what broke the earlier trials. You can look away.", flush=True)
    print("  2. A ~6s gap, then WATCH #1: the panel should still be NOISE. If it is", flush=True)
    print("     anything else, say so -- the decoy did not persist and the run is VOID.", flush=True)
    print(f"  3. GREEN appears and is held {dwell:.0f}s. Confirm it is green.", flush=True)
    print("  4. A ~6s gap, then WATCH #2 -- THE QUESTION:", flush=True)
    print("       GREEN -- the write survived.", flush=True)
    print("       NOISE -- the write was lost; the panel reverted to the committed decoy.", flush=True)
    print("  5. CLEANUP: the ordinary clock face. Not a result.", flush=True)
    print("============================================================================", flush=True)
    print("", flush=True)


async def reconnect(client: IDotMatrixClient) -> bool:
    await client.disconnect()
    await asyncio.sleep(BLE_GAP_SECONDS)
    await client.connect()
    await asyncio.sleep(SETTLE_SECONDS)
    snapshot = client.snapshot()
    print(f"    transport: {snapshot}", flush=True)
    return snapshot.is_connected


async def main(sequence: str, dwell: float) -> None:
    print(f"sequence: {sequence} -- {SEQUENCES[sequence]}  [dwell {dwell:.0f}s]", flush=True)
    print_visual_script(dwell)

    data = make_big_gif(GIF_SEED)
    print(f"decoy fixture: seed-{GIF_SEED}, {len(data)} bytes", flush=True)
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, SCREEN) as client:
        print(f"\n=== STEP 1: activate the noise decoy and hold {PERSIST_SECONDS:.0f}s to COMMIT it", flush=True)
        recognised = await client.gif.activate_stored(data)
        print(f"    activate_stored -> {recognised}", flush=True)
        if not recognised:
            print("    the device does NOT hold seed-215; run probe_p2b_terminal_status.py", flush=True)
            print("    fresh first. VOID -- stopping before wasting the wait.", flush=True)
            return
        await asyncio.sleep(PERSIST_SECONDS)

        print("\n=== STEP 2: reconnect, then WATCH #1 -- is it STILL NOISE?", flush=True)
        if not await reconnect(client):
            print("    RECONNECT FAILED -- run is void.", flush=True)
            return
        print("    (noise = the decoy committed, the trial is valid.", flush=True)
        print("     anything else = decoy did NOT persist, the run is VOID -- say so.)", flush=True)
        await asyncio.sleep(WATCH_SECONDS)

        print(f"\n=== STEP 3: write GREEN {GREEN}, hold {dwell:.0f}s", flush=True)
        await client.color.show(GREEN)
        await asyncio.sleep(dwell)

        print("\n=== STEP 4: reconnect, then WATCH #2 -- THE QUESTION", flush=True)
        if not await reconnect(client):
            print("    RECONNECT FAILED -- run is void.", flush=True)
            return
        print("    GREEN -- the write survived.", flush=True)
        print("    NOISE -- lost; reverted to the committed decoy.", flush=True)
        await asyncio.sleep(WATCH_SECONDS)

        print("\n--- cleanup ---", flush=True)
        await client.clock.show()
        print("panel restored to the clock face.", flush=True)

    print("disconnected.", flush=True)


asyncio.run(main(*select(sys.argv[1:])))
