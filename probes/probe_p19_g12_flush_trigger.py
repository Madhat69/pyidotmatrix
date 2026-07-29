"""P19 G12 -- does the commit run on WALL CLOCK, or does the DISCONNECT flush it?

WHAT G11 SETTLED, AND WHAT IT DID NOT
-------------------------------------
G11 (2026-07-29) wrote WHITE, held it just 2.1 s with the link up, and the panel
booted WHITE after a power cut 45.7 s later. So a 2 s hold commits -- while G8
and G9 both had 8 s holds failing. **Link-up dwell is not what drives the flash
commit**, and every "dwell" number in G5/G8/G9 was really total elapsed time,
with the operator's unrecorded reaction time setting it.

But two hypotheses both predict G11's white, and it separates neither:

  WALL CLOCK      the commit runs on elapsed time since the write, link up or
                  down. 47.9 s total was plenty.
  DISCONNECT FLUSH the clean teardown itself triggers the flush. Dwell and post
                  are both irrelevant; any tidy disconnect commits.

G8's `no-arm` leans against the flush model -- it disconnected cleanly and still
did not commit -- but G8 is exactly the run this series no longer trusts.

THE TWO SEQUENCES, AND WHY THEY CANNOT BOTH SURVIVE
---------------------------------------------------
`short-post`  Write, 2 s dwell, disconnect, and the operator pulls the plug ~5 s
              later. Total ~8 s, with a clean disconnect in it.
                  commits     -> the DISCONNECT flushes (elapsed time was far too
                                 short to explain it), and G8's no-arm was noise.
                  no commit   -> WALL CLOCK, now bracketed 8 s < t <= 48 s.

`live-cut`    Write, then never disconnect at all: the operator pulls the plug
              ~60 s later with the link still UP. There is no clean teardown
              anywhere in this run.
                  commits     -> WALL CLOCK confirmed; the disconnect plays no
                                 part whatsoever.
                  no commit   -> the flush NEEDS the disconnect, and elapsed time
                                 alone does nothing.

No reading leaves both models standing.

THE INSTRUMENT
--------------
G10 validated the advertisement watch: the panel advertises ~9 Hz while powered
and unconnected, so the power cut is pinned to the last advertisement seen --
~110 ms typically, ~2.1 s worst case.

The cadence baseline is taken BEFORE connecting here, not after disconnecting as
G11 did. G11's 12 s post-disconnect baseline made a short POST impossible, which
is precisely what `short-post` needs to measure.

`live-cut` uses a better instrument still: with the link up the panel is not
advertising, so the power cut is observed as the CONNECTION DROPPING. Note the
systematic offset -- the host only notices after the BLE supervision timeout, so
the recorded instant runs a few seconds late. It does not matter: that sequence's
reading is the boot colour, and its elapsed time only needs to be "about a
minute". auto_reconnect is OFF, or the transport would paper over the very event
being measured.

COLOUR DISCIPLINE
-----------------
Each trial must use a colour the current flash state is NOT, so "committed" and
"reverted" are never the same picture -- the confound that voided two trials on
2026-07-28. The colour is an argument rather than a per-sequence constant
because these trials repeat; pick one the LAST trial did not leave in flash.

SAFETY
------
One fullscreen colour per run. No reset, no brightness, no eco, no flip, no RTC
write, no GIF, no graffiti, no experimental namespace, nothing near the password
or UART surface. No reconnect anywhere -- that is condition (B) and would
confound the measurement. The panel is deliberately LEFT on the trial colour;
restoring it would overwrite the state the power cycle reads.

USAGE
-----
    python probes/probe_p19_g12_flush_trigger.py short-post magenta
    python probes/probe_p19_g12_flush_trigger.py live-cut cyan

RESULT (2026-07-29): **WALL CLOCK. The commit runs on elapsed time since the
write, 5 s < t <= 10.3 s, and the link state is irrelevant.** Three trials, read
by boot colour, with G11's for context:

    trial     total write->cut   clean disconnect?   committed
    yellow          < 5 s              yes              NO
    magenta        ~10.3 s             yes              yes
    white (G11)     47.9 s             yes              yes
    cyan           ~69 s               NO -- live link  yes

`live-cut` (cyan) is the decisive one: the plug killed a LIVE connection at
69.2 s, there was no clean teardown anywhere in the run, and it committed
anyway. DISCONNECT-FLUSH IS DEAD. Combined with G11 (2 s dwell committing), so
is DWELL.

`short-post` at <5 s is the negative that makes the rest trustworthy. It rules
out a third model neither of the others excluded -- that the POWER CUT ITSELF
flushes on the way down -- because here a power cut flushed nothing. It is also
the first non-commit in this whole series measured with a validated instrument,
and it gives the lower bracket.

`short-post` at ~10.3 s (magenta) did NOT discriminate and is recorded as such:
designed for ~7 s, it landed above the 8 s where G9's lime committed, so a
wall-clock threshold under ~10 s explains it as well as a flush would. It counts
only as an upper bracket, never as evidence for the disconnect model.

THE BACK CATALOGUE RECONCILES with no contradictions left: G8's `no-arm` (8 s
hold, operator pulled fast) sat under the threshold; G9's lime (8 s hold,
operator slower) sat over it. Same nominal dwell, opposite outcomes, one
uncontrolled variable -- reaction time -- explaining both.

STILL OPEN: the threshold is bracketed 5 s < t <= 10.3 s, not pinned. Cheap to
narrow now that G10's instrument exists -- a couple of trials near 7 s, a fresh
colour each. Nothing in the SDK needs it: ~15 s between the last write and any
power loss is safe under every surviving reading.

PROBE BUG FOUND AND FIXED (first `short-post` attempt, VOID): a connected panel
does not advertise, so the last timestamp was already older than the dead-gap
threshold the instant the link dropped. The detector fired on pre-connection
data and reported a NEGATIVE post before the operator touched anything. The
watch now waits for a FRESH advertisement after the disconnect before arming,
and falls back to an explicitly BOUNDED post if the plug beats it. G11 never had
this bug -- its baseline ran after the disconnect, always on live data.
"""

import asyncio
import itertools
import statistics
import sys
import time

from bleak import AdvertisementData, BleakScanner
from bleak.backends.device import BLEDevice

from pyidotmatrix import BleTransport, IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

# Each sequence owns a colour, so a run can never be read against the wrong
# hypothesis and two trials can never be confused at the panel.
SEQUENCES = ("short-post", "live-cut")

# Trials repeat, so the colour is chosen per run rather than bound to the
# sequence: each one must differ from whatever the LAST trial put in flash, or
# "committed" and "reverted" are the same picture. That confound voided two
# trials on 2026-07-28.
PALETTE: dict[str, tuple[int, int, int]] = {
    "magenta": (255, 0, 200),
    "cyan": (0, 220, 220),
    "yellow": (255, 200, 0),
    "red": (255, 0, 0),
    "lime": (120, 255, 0),
    "white": (255, 255, 255),
}

DWELL_SECONDS = 2.0
SETTLE_SECONDS = 2.0
LIVE_CUT_HINT_SECONDS = 60.0

BASELINE_SECONDS = 12.0
DEAD_GAP_FLOOR = 4.0
DEAD_GAP_CEILING = 20.0
DEAD_GAP_SAFETY_FACTOR = 3.0
POLL_SECONDS = 0.2

# How long to wait for the panel to start advertising again after a disconnect
# before giving up on pinning the cut. Generous: it is only a fallback bound.
RESUME_TIMEOUT_SECONDS = 4.0

WAIT_FOR_PULL_SECONDS = 600.0


def print_usage() -> None:
    print("usage: python probes/probe_p19_g12_flush_trigger.py <sequence> <colour>", flush=True)
    print("", flush=True)
    print("  short-post -- 2s dwell, clean disconnect, plug pulled as soon as you can.", flush=True)
    print("                Used now to reproduce a FAILURE at a short total time.", flush=True)
    print("  live-cut   -- 2s dwell, NEVER disconnects, plug pulled ~60s later with", flush=True)
    print("                the link up. Answered on 2026-07-29: commits (wall clock).", flush=True)
    print("", flush=True)
    print(f"colour: {', '.join(PALETTE)}", flush=True)
    print("", flush=True)
    print("Use a colour the panel's CURRENT flash state is not, and a different one", flush=True)
    print("each trial -- the boot colour is what tells you which trial committed.", flush=True)


def select(argv: list[str]) -> tuple[str, str]:
    """Validated before any BLE contact, so a typo cannot burn a panel session."""
    if len(argv) != 2:
        print(f"error: expected exactly 2 arguments, got {len(argv)}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    sequence = argv[0].lower()
    if sequence not in SEQUENCES:
        print(f"error: unknown sequence {argv[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    colour = argv[1].lower()
    if colour not in PALETTE:
        print(f"error: unknown colour {argv[1]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    return sequence, colour


def print_visual_script(sequence: str, colour: str) -> None:
    """EVERY visual of the run, in order, printed before any BLE contact."""
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER ============================================", flush=True)
    print("  0. BEFORE: whatever is on the panel now. Not a measurement.", flush=True)
    print(f"  1. {BASELINE_SECONDS:.0f}s of NOTHING while the advertising cadence is baselined.", flush=True)
    print("     The panel is not connected to yet. Do not touch it.", flush=True)
    print(f"  2. {colour.upper()} fills the panel and is held {DWELL_SECONDS:.0f}s.", flush=True)
    if sequence == "short-post":
        print("  3. The link drops. The colour STAYS on screen.", flush=True)
        print("  4. YOU: pull the power ~5s after the colour appeared. Short is the", flush=True)
        print("     whole point -- but not INSTANT, or the link is still up and this", flush=True)
        print("     becomes the live-cut experiment instead. Count to five.", flush=True)
    else:
        print("  3. The link STAYS UP and the probe holds it, idle, saying nothing.", flush=True)
        print(f"  4. YOU: pull the power about {LIVE_CUT_HINT_SECONDS:.0f}s after the colour appeared.", flush=True)
        print("     Roughly is fine. There is no clean disconnect in this run at all.", flush=True)
    print("  5. YOU: plug it back in and report the BOOT colour.", flush=True)
    print(f"       BOOTS {colour:8s}    -> this trial committed.", flush=True)
    print("       BOOTS ANYTHING ELSE -> it did not, and the colour you see names", flush=True)
    print("           the last trial that did.", flush=True)
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


async def baseline_cadence(stamps: list[float]) -> tuple[float, float]:
    """Learns the advertising cadence BEFORE connecting, and returns
    (worst_gap, dead_gap). Doing this up front is what lets POST be short."""
    print(f"=== BASELINE {BASELINE_SECONDS:.0f}s (not connected yet) -- leave the panel alone ===", flush=True)
    await asyncio.sleep(BASELINE_SECONDS)
    if len(stamps) < 2:
        print(f"\n  FAILED: saw {len(stamps)} advertisement(s) from {ADDRESS}.", flush=True)
        print("  Nothing has been written, so nothing is lost. Is the panel powered,", flush=True)
        print("  and is anything else (the app, the daemon) holding a connection?", flush=True)
        raise SystemExit(1)
    _, worst_gap = summarise_gaps(stamps)
    dead_gap = min(DEAD_GAP_CEILING, max(DEAD_GAP_FLOOR, worst_gap * DEAD_GAP_SAFETY_FACTOR))
    print(f"  {len(stamps)} advertisements, worst gap {worst_gap * 1000:.0f} ms", flush=True)
    print(f"  silence meaning 'power cut': {dead_gap:.1f}s", flush=True)
    return worst_gap, dead_gap


async def run_short_post(
    client: IDotMatrixClient, rgb: tuple[int, int, int], colour: str, stamps: list[float], dead_gap: float
) -> None:
    """Clean disconnect, then the shortest power cut the operator can manage."""
    await client.connect()
    try:
        print(f"  transport: {client.snapshot()}", flush=True)
        print(f"\n=== writing {colour}, holding {DWELL_SECONDS:.0f}s ===", flush=True)
        await client.color.show(rgb)
        written_at = time.monotonic()
        await asyncio.sleep(DWELL_SECONDS)
    finally:
        await client.disconnect()
    disconnected_at = time.monotonic()

    print("\n=== NOW: PULL THE POWER. Sooner is better. ===", flush=True)
    seen_at_disconnect = len(stamps)

    # A connected panel does not advertise, so stamps[-1] is stale the moment the
    # link drops -- older than dead_gap already, which fires the detector on data
    # from before the trial even started. (It did exactly that on the first run,
    # reporting a NEGATIVE post.) Arm only once a FRESH advertisement proves the
    # panel is both alive and being heard.
    resume_deadline = time.monotonic() + RESUME_TIMEOUT_SECONDS
    while len(stamps) == seen_at_disconnect:
        if time.monotonic() > resume_deadline:
            print(f"\n  no advertisement in the {RESUME_TIMEOUT_SECONDS:.0f}s after the disconnect.", flush=True)
            print("  Either you pulled the plug inside that window -- which is a", flush=True)
            print("  legitimately SHORT post, just an unpinned one -- or the panel did", flush=True)
            print("  not resume advertising. The cut cannot be timed either way.", flush=True)
            print(f"\n  DWELL (link up)   : {disconnected_at - written_at:6.1f}s", flush=True)
            print(f"  POST  (link down) : <= {RESUME_TIMEOUT_SECONDS:.1f}s  (bounded, not measured)", flush=True)
            print("\n  Report the boot colour anyway: a bounded short post still answers", flush=True)
            print("  the question, it just cannot contribute a threshold datum.", flush=True)
            return
        await asyncio.sleep(POLL_SECONDS)
    print(f"  watch live again ({len(stamps) - seen_at_disconnect} advertisement(s) since the disconnect)", flush=True)

    armed = time.monotonic()
    while time.monotonic() - stamps[-1] < dead_gap:
        if time.monotonic() - armed > WAIT_FOR_PULL_SECONDS:
            print(f"\n  gave up: no power cut in {WAIT_FOR_PULL_SECONDS:.0f}s. Trial VOID -- the", flush=True)
            print("  colour has now had far longer than intended to commit.", flush=True)
            raise SystemExit(1)
        await asyncio.sleep(POLL_SECONDS)
    lost_at = stamps[-1]

    print("\n=== POWER CUT DETECTED ===================================================", flush=True)
    print(f"  DWELL (link up)    : {disconnected_at - written_at:6.1f}s", flush=True)
    print(f"  POST  (link down)  : {lost_at - disconnected_at:6.1f}s", flush=True)
    print(f"  TOTAL write -> cut : {lost_at - written_at:6.1f}s", flush=True)
    print("==========================================================================", flush=True)
    print(f"\n  {colour.upper()} -> committed even at this total. If the total is only a few", flush=True)
    print("           seconds, suspect the POWER CUT ITSELF flushes, and no dwell", flush=True)
    print("           model is needed to explain anything.", flush=True)
    print("  ANYTHING ELSE -> a genuine NON-COMMIT, reproduced with the validated", flush=True)
    print("           watch. Rules out a brownout flush and brackets the wall-clock", flush=True)
    print("           threshold ABOVE this total.", flush=True)


async def run_live_cut(client: IDotMatrixClient, rgb: tuple[int, int, int], colour: str) -> None:
    """Holds the link open until the power cut kills it. No clean teardown."""
    await client.connect()
    print(f"  transport: {client.snapshot()}", flush=True)
    print(f"\n=== writing {colour}, then HOLDING THE LINK OPEN ===", flush=True)
    await client.color.show(rgb)
    written_at = time.monotonic()
    await asyncio.sleep(SETTLE_SECONDS)

    print(f"\n=== NOW: hold ~{LIVE_CUT_HINT_SECONDS:.0f}s, then PULL THE POWER. ===", flush=True)
    print("    The link stays up until your plug kills it. Roughly is fine.", flush=True)
    while client.snapshot().is_connected:
        if time.monotonic() - written_at > WAIT_FOR_PULL_SECONDS:
            print(f"\n  gave up: still connected after {WAIT_FOR_PULL_SECONDS:.0f}s. Trial VOID.", flush=True)
            await client.disconnect()
            raise SystemExit(1)
        await asyncio.sleep(POLL_SECONDS)
    dropped_at = time.monotonic()

    print("\n=== CONNECTION LOST -- that was the plug ==================================", flush=True)
    print(f"  write -> link loss : {dropped_at - written_at:6.1f}s", flush=True)
    print("  (runs a few seconds late: the host only notices after the BLE", flush=True)
    print("   supervision timeout. Immaterial here -- the reading is the colour.)", flush=True)
    print("  NO clean disconnect happened at any point in this run.", flush=True)
    print("==========================================================================", flush=True)
    print(f"\n  {colour.upper()} -> WALL CLOCK; the disconnect plays no part.", flush=True)
    print("  ANYTHING ELSE -> the flush NEEDS the disconnect; elapsed time alone", flush=True)
    print("            does nothing.", flush=True)


async def main(sequence: str, colour: str) -> None:
    rgb = PALETTE[colour]
    print(f"sequence: {sequence}, colour {colour.upper()} {rgb}", flush=True)
    print_visual_script(sequence, colour)

    stamps: list[float] = []

    def on_detect(device: BLEDevice, adv: AdvertisementData) -> None:
        if device.address.upper() == ADDRESS.upper():
            stamps.append(time.monotonic())

    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    try:
        _, dead_gap = await baseline_cadence(stamps)
        print("\nconnecting ...", flush=True)
        # auto_reconnect off: live-cut MEASURES the drop, and a transport that
        # quietly reconnects would both hide it and add a condition (B) reconnect.
        client = IDotMatrixClient(SCREEN, transport=BleTransport(mac_address=ADDRESS, auto_reconnect=False))
        if sequence == "short-post":
            await run_short_post(client, rgb, colour, stamps, dead_gap)
        else:
            await run_live_cut(client, rgb, colour)
    finally:
        await scanner.stop()

    print("\n  Plug it back in and report the BOOT colour.", flush=True)
    print("(panel left as-is deliberately -- restoring would overwrite the measurement)", flush=True)


asyncio.run(main(*select(sys.argv[1:])))
