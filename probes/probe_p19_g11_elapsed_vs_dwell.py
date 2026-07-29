"""P19 G11 -- is the flash commit driven by DWELL, or by WALL CLOCK?

THE QUESTION
------------
Every earlier probe in this series assumed the variable was DWELL: how long the
colour is held with the link UP. G8 and G9 walked ladders in it, disagreed with
each other at 8 s, and the resulting "a reconnect ARMS the commit" claim had to
be retracted.

The retraction's post-mortem raised a simpler explanation that no probe had
tested: **the commit may not care about the link at all.** If it runs on wall
clock from the moment of the write, continuing happily after the link drops,
then dwell was never the manipulated variable -- total elapsed time to the power
cut was, and the operator's unrecorded reaction time was setting it.

That single substitution explains the whole contradiction:

    trial            dwell   real elapsed to cut        committed
    G8 `no-arm`        8 s   operator pulled quickly    no
    G9 lime            8 s   operator was slower        yes
    G9 15/30/60 s   15-60 s  necessarily long           yes

It also explains G8's "arming" without any arming: the `arm` run performed a
reconnect, which costs ~10 s of wall clock its control never spent.

HOW THIS PROBE SEPARATES THEM
-----------------------------
Two intervals are now measured separately instead of being conflated:

    DWELL -- write -> disconnect, with the link UP. Chosen by the argument.
    POST  -- disconnect -> power cut, with the link DOWN. Chosen by the operator
             and MEASURED, via G10's advertisement watch (validated 2026-07-29:
             cut instant pinned to ~110 ms typical, ~2.1 s worst case).

The decisive trial is SHORT DWELL, LONG POST -- 2 s dwell, pull the plug a
minute or two later:

    boots the trial colour   -> a 2 s dwell was enough, so dwell is NOT the
                                variable. The commit runs on wall clock with the
                                link down, and every ladder in this series
                                collapses into one axis.
    boots the previous colour-> dwell is real, and for the first time it is
                                isolated from operator timing.

Either answer is worth more than the four rungs of G9.

WHY THE OPERATOR NO LONGER HAS A DEADLINE
-----------------------------------------
Pull the plug WHENEVER. The watch records POST, so there is no target to hit and
no reaction time in the measurement. This is the fix for the flaw that voided
G8/G9: the interval is not controlled, it is observed. A scatter of trials at
whatever times they happened to land maps the curve better than a rigid ladder.

COLOUR DISCIPLINE
-----------------
Each trial must use a colour the current flash state is NOT, so "committed" and
"reverted" are never the same picture -- the confound that voided two dwell
trials on 2026-07-28. Flash currently holds LIME (G9's 8 s retry, re-confirmed
by G10's power cycle on 2026-07-29), so start with WHITE.

There is deliberately NO reconnect anywhere: a reconnect is condition (B) and
would confound the measurement.

SAFETY
------
One fullscreen colour per run. No reset, no brightness, no eco, no flip, no RTC
write, no GIF, no graffiti, no experimental namespace, nothing near the password
or UART surface. The panel is deliberately LEFT on the trial colour -- restoring
it would overwrite the very state the power cycle reads.

USAGE
-----
    python probes/probe_p19_g11_elapsed_vs_dwell.py <dwell_seconds> <colour>

    e.g. python probes/probe_p19_g11_elapsed_vs_dwell.py 2 white

RESULT (2026-07-29): **DWELL IS NOT THE VARIABLE. Run: WHITE, 2.1 s link-up
dwell, power cut 45.7 s after the disconnect (47.9 s total). BOOTED WHITE.**

A 2 s hold committed, while G8 and G9 both had 8 s holds failing. So link-up
dwell does not drive the flash commit, and every "dwell" number in G5/G8/G9 was
total elapsed time in disguise with the operator's reaction time setting it.
That also explains G8's "arming" without any arming: its `arm` run performed a
reconnect, buying ~10 s of wall clock its control never spent.

WHAT THIS RUN COULD NOT SEPARATE -- both models predict white here:

    WALL CLOCK        commit runs on elapsed time since the write, link up or
                      down; 47.9 s was plenty.
    DISCONNECT FLUSH  the clean teardown triggers it; duration irrelevant.

G12 (probes/probe_p19_g12_flush_trigger.py) settled it: a run that NEVER
disconnected -- the plug killed a live link at ~69 s -- still committed, so the
disconnect plays no part. **The commit runs on wall clock, 5 s < t <= 10.3 s,
independent of link state.**

A note on this probe's own design, since it matters for reuse: its cadence
baseline runs AFTER the disconnect, so its watch was always looking at live
advertisements. G12 moved the baseline BEFORE the connection to allow a short
POST, and that exposed a bug this probe never had -- a connected panel does not
advertise, so a pre-connection timestamp is already stale when the link drops.
"""

import asyncio
import itertools
import statistics
import sys
import time

from bleak import AdvertisementData, BleakScanner
from bleak.backends.device import BLEDevice

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32
NAME_PREFIX = "IDM-"

# Deliberately far apart, and none close to the orange/green/blue this series has
# already used, so a boot reading is never a judgement call.
PALETTE: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255),
    "magenta": (255, 0, 200),
    "cyan": (0, 220, 220),
    "yellow": (255, 200, 0),
    "red": (255, 0, 0),
    "lime": (120, 255, 0),
}

DWELL_MIN, DWELL_MAX = 2.0, 600.0
SETTLE_SECONDS = 2.0

# Re-derived per run rather than hardcoded from G10: the advertiser is bursty and
# a stale threshold could forge a cut on a quieter day.
WATCH_BASELINE_SECONDS = 12.0
DEAD_GAP_FLOOR = 4.0
DEAD_GAP_CEILING = 20.0
DEAD_GAP_SAFETY_FACTOR = 3.0
POLL_SECONDS = 0.2

WAIT_FOR_PULL_SECONDS = 600.0


def print_usage() -> None:
    print("usage: python probes/probe_p19_g11_elapsed_vs_dwell.py <dwell_seconds> <colour>", flush=True)
    print("", flush=True)
    print(f"dwell_seconds: {DWELL_MIN:.0f}..{DWELL_MAX:.0f}, how long the colour is held with the", flush=True)
    print("               link UP. Use 2 for the decisive short-dwell trial.", flush=True)
    print(f"colour       : {', '.join(PALETTE)}", flush=True)
    print("", flush=True)
    print("Use a colour the panel's CURRENT flash state is not, and a different one", flush=True)
    print("each trial -- the boot colour is what tells you which trial committed.", flush=True)


def select(argv: list[str]) -> tuple[float, str]:
    """Validated before any BLE contact, so a typo cannot burn a panel session."""
    if len(argv) != 2:
        print(f"error: expected exactly 2 arguments, got {len(argv)}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    try:
        dwell = float(argv[0])
    except ValueError:
        print(f"error: dwell_seconds must be a number, got {argv[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2) from None
    if not DWELL_MIN <= dwell <= DWELL_MAX:
        print(f"error: dwell_seconds must be {DWELL_MIN:.0f}..{DWELL_MAX:.0f}, got {dwell:g}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    colour = argv[1].lower()
    if colour not in PALETTE:
        print(f"error: unknown colour {argv[1]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    return dwell, colour


def print_visual_script(dwell: float, colour: str) -> None:
    """EVERY visual of the run, in order, printed before any BLE contact."""
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER ============================================", flush=True)
    print("  0. BEFORE: whatever is on the panel now. Not a measurement.", flush=True)
    print(f"  1. {colour.upper()} fills the panel, held {dwell:.0f}s with the link UP.", flush=True)
    print("     NO reconnect happens at any point -- that is condition (B) and", flush=True)
    print("     would confound this measurement.", flush=True)
    print("  2. The link drops. The colour STAYS on screen. The probe keeps", flush=True)
    print("     watching the panel's advertisements from a distance.", flush=True)
    print(f"  3. {WATCH_BASELINE_SECONDS:.0f}s of watch baseline -- DO NOT pull the plug yet.", flush=True)
    print("  4. YOU: pull the power WHENEVER you like after that. No target, no", flush=True)
    print("     deadline. The probe measures when you did it to a fraction of a", flush=True)
    print("     second, which is the entire point of this design.", flush=True)
    print("  5. YOU: plug it back in, and report the BOOT colour.", flush=True)
    print(f"       BOOTS {colour.upper():8s} -> this trial committed.", flush=True)
    print("       BOOTS LIME     -> it did not; flash still holds the old state.", flush=True)
    print("============================================================================", flush=True)
    print("", flush=True)


def summarise_gaps(stamps: list[float]) -> tuple[float, float]:
    """Returns (median, worst) interval between consecutive advertisements.

    Takes a snapshot: the scanner callback appends from another task, and a
    sequence that grows mid-calculation is a bug waiting to happen.
    """
    snapshot = list(stamps)
    gaps = [b - a for a, b in itertools.pairwise(snapshot)]
    return statistics.median(gaps), max(gaps)


async def main(dwell: float, colour: str) -> None:
    rgb = PALETTE[colour]
    print(f"trial: {dwell:.0f}s dwell, colour {colour.upper()} {rgb}", flush=True)
    print_visual_script(dwell, colour)

    print("connecting ...", flush=True)
    client = IDotMatrixClient(SCREEN, mac_address=ADDRESS)
    await client.connect()
    try:
        print(f"  transport: {client.snapshot()}", flush=True)
        print(f"\n=== writing {colour.upper()}, holding {dwell:.0f}s (no reconnect) ===", flush=True)
        await client.color.show(rgb)
        written_at = time.monotonic()
        await asyncio.sleep(SETTLE_SECONDS)
        print(f"    confirm the panel is {colour.upper()}.", flush=True)
        await asyncio.sleep(max(0.0, dwell - SETTLE_SECONDS))
    finally:
        await client.disconnect()
    disconnected_at = time.monotonic()
    print(f"  link down at write+{disconnected_at - written_at:.1f}s", flush=True)

    stamps: list[float] = []

    def on_detect(device: BLEDevice, adv: AdvertisementData) -> None:
        if device.address.upper() == ADDRESS.upper():
            stamps.append(time.monotonic())

    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    try:
        print(f"\n=== WATCH BASELINE {WATCH_BASELINE_SECONDS:.0f}s -- do NOT pull yet ===", flush=True)
        await asyncio.sleep(WATCH_BASELINE_SECONDS)
        if len(stamps) < 2:
            print(f"\n  FAILED: saw {len(stamps)} advertisement(s) after disconnect.", flush=True)
            print("  Without the watch this trial cannot be timed, so it is void.", flush=True)
            print(f"  The panel is left {colour.upper()}; do NOT power-cycle -- a reading", flush=True)
            print("  now would be untimed and would waste the colour.", flush=True)
            raise SystemExit(1)

        _, worst_gap = summarise_gaps(stamps)
        dead_gap = min(DEAD_GAP_CEILING, max(DEAD_GAP_FLOOR, worst_gap * DEAD_GAP_SAFETY_FACTOR))
        print(f"  watch live: {len(stamps)} advertisements, worst gap {worst_gap * 1000:.0f} ms", flush=True)
        print(f"  silence meaning 'power cut': {dead_gap:.1f}s", flush=True)

        print("\n=== NOW: PULL THE PANEL'S POWER. Any moment you like. ===", flush=True)
        armed = time.monotonic()
        while time.monotonic() - stamps[-1] < dead_gap:
            if time.monotonic() - armed > WAIT_FOR_PULL_SECONDS:
                print(f"\n  gave up: no power cut seen in {WAIT_FOR_PULL_SECONDS:.0f}s.", flush=True)
                print("  Nothing was harmed, but this trial is void -- and note the", flush=True)
                print("  colour has now had far longer than intended to commit.", flush=True)
                raise SystemExit(1)
            await asyncio.sleep(POLL_SECONDS)
        lost_at = stamps[-1]
    finally:
        await scanner.stop()

    post = lost_at - disconnected_at
    total = lost_at - written_at
    print("\n=== POWER CUT DETECTED ===================================================", flush=True)
    print(f"  DWELL (link up)     : {disconnected_at - written_at:6.1f}s", flush=True)
    print(f"  POST  (link down)   : {post:6.1f}s", flush=True)
    print(f"  TOTAL write -> cut  : {total:6.1f}s   +/- one advertising gap", flush=True)
    print("==========================================================================", flush=True)
    print("\n  Plug it back in and report the BOOT colour.", flush=True)
    held = disconnected_at - written_at
    print(f"    {colour.upper()} -> committed on only {held:.0f}s of link-up dwell,", flush=True)
    print(f"           so wall clock ({total:.0f}s), not dwell, drives the commit.", flush=True)
    print("    LIME  -> did not commit; dwell matters after all, and this is the", flush=True)
    print("           first trial where it is cleanly separated from timing.", flush=True)
    print("(panel left as-is deliberately -- restoring would overwrite the measurement)", flush=True)


asyncio.run(main(*select(sys.argv[1:])))
