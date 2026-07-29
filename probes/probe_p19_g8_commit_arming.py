"""P19 G8 -- does a prior reconnect ARM THE FLASH COMMIT, or only the display?

WHY THIS PROBE EXISTS
---------------------
G7 showed condition (B) -- a prior disconnect/reconnect in the same session --
letting a 10-second-old GREEN write survive the next reconnect, a dwell that had
died six times without one. Afterwards the operator power-cycled the panel and it
booted to GREEN, even though G7's cleanup had left the CLOCK on screen.

That suggests (B) does more than keep the write on screen: it appears to ARM or
ACCELERATE the FLASH COMMIT, since under condition (A) alone a write needs
100-180 s to commit and green had nothing like that.

But it is one observation with an unexcluded alternative: green stayed up for
roughly 28 s in total across G7's final watch and cleanup, so it may simply have
committed on its own and (B) may have nothing to do with flash at all. One run
separates the two.

THE DISCRIMINATOR
-----------------
Blue is written AFTER a reconnect and held only 8 s -- far too short for an
ordinary commit -- and the CURRENT boot state is green, from G7. So:

    boots BLUE   -> blue committed in ~8 s. (B) arms the commit. The mechanical
                    reading is right.
    boots GREEN  -> blue never committed; the flash slot still holds G7's green.
                    (B) governs the DISPLAY only, and green's commit was
                    ordinary dwell. The claim must be narrowed.

Blue rather than orange or green purely so neither prior state can be mistaken
for this run's.

A SECOND READING, free
----------------------
After the 8 s hold this probe disconnects and pauses before exiting, so the
operator can also see whether BLUE SURVIVES THE DISCONNECT on screen. That is
condition (B)'s display effect, independent of what flash ends up holding. The
two readings can disagree -- display and flash are different states (see
capabilities.py's display.persistence_matrix) -- and that disagreement would
itself be the finding.

WHAT THE OPERATOR DOES
----------------------
  1. Watch for blue, then for what the disconnect leaves on screen.
  2. THEN PULL THE PANEL'S POWER, plug it back in, and report the boot colour.
     The probe cannot do this and exits without waiting.

SAFETY
------
One reconnect and one fullscreen colour. No reset, no brightness, no eco, no
flip, no RTC write, no GIF, no graffiti, no experimental namespace, nothing near
the password or UART surface. The panel is deliberately LEFT on this run's
colour rather than restored -- restoring would overwrite the very state being
measured.

USAGE
-----
    python probes/probe_p19_g8_commit_arming.py arm      # BLUE, after a reconnect
    python probes/probe_p19_g8_commit_arming.py no-arm   # MAGENTA, no reconnect

The argument is mandatory. Runtime ~45 s (arm) / ~25 s (no-arm), plus your power
cycle. Each sequence writes a colour the current flash state is NOT: reusing a
colour already in flash makes reversion and survival the same picture.

RESULT (2026-07-28): **RETRACTED IN PART. The commit claim below did NOT hold
up; the display claim is untouched. Read this box before the account beneath it.**

**FULLY EXPLAINED 2026-07-29 -- DO NOT RE-RUN THIS PROBE.** G10/G11/G12 showed
the flash commit runs on WALL CLOCK from the write (5 s < t <= 10.3 s),
independent of link state: a 2 s hold committed, and a run with no clean
disconnect at all committed too. This probe's matched pair was therefore two
different operator reaction times, not two arming states -- and its `arm` run
additionally spent ~10 s of wall clock on the reconnect that its control never
spent. Nothing here needs re-measuring. See probes/probe_p19_g12_flush_trigger.py.

This probe concluded that a prior reconnect ARMS THE FLASH COMMIT, on the
strength of a matched pair: `arm` (reconnect, 8 s hold) booted its own colour,
`no-arm` (no reconnect, same 8 s) booted the previous one. One variable, opposite
outcomes.

probe_p19_g9_commit_ladder.py then re-ran 8 s WITHOUT a reconnect and it DID
commit. So 8 s commits inconsistently unassisted, the pair is not a contrast, and
**"(B) arms the flash commit" is UNPROVEN.**

Root cause, and it is this probe's flaw as much as G9's: **the interval between
the disconnect and the operator's power cycle is never controlled.** If the commit
can finish after the link drops, that unrecorded interval is part of the effective
dwell, and two runs nominally at "8 s" can differ by a minute of real elapsed
time. Neither probe measures what it claims at the boundary.

WHAT STILL STANDS: condition (B)'s DISPLAY effect. G7 showed green surviving a
reconnect at 10 s where the reconnect ladder died at 8, 30, 60, 75, 90 and 100 s.
That evidence does not depend on any power cycle and is unaffected.

The original account follows, kept for provenance:

--- ORIGINAL (superseded) -----------------------------------------------------
**a prior reconnect ARMS THE FLASH COMMIT.**

Operator: `reconnect -> GREEN -> green (~1 s) -> BLUE -> power cycle -> BLUE`.

1. The step-1 reconnect reverted the panel to **GREEN** for about a second --
   G7's colour, i.e. the flash state -- which is the revert-to-persisted
   behaviour caught in the act, and independent confirmation that green really
   was committed.
2. BLUE was then written and held **8 s**.
3. WATCH #1: blue STAYED through the disconnect.
4. **The panel BOOTED TO BLUE after a physical power cycle.**

So an 8-second-old write reached FLASH. Under condition (A) alone that takes
100-180 s (the g5 ladder). The only difference here is the reconnect that
preceded the write.

=> **Condition (B) is a COMMIT mechanism, not a display quirk.** A prior
disconnect/reconnect in the session causes subsequent writes to commit to flash
almost immediately -- roughly an order of magnitude faster than the lazy timer.
This closes the "mechanism is OPEN" note that had stood against (B) since it was
first seen with `--preamble ble gif`.

The alternative left open by G7 -- that green had simply committed on its own
during the ~28 s it was up -- is excluded: blue had only 8 s and no dwell of its
own, and still made it to flash.

THE SETTLED MODEL, both conditions now mechanically stated:

    (A) no prior reconnect  -> lazy commit, 100 s < t <= 180 s
    (B) prior reconnect     -> commit armed, <= 8 s

GLANCEOS: the double-tap connect (`d514e5a`) is now EXPLAINED rather than merely
justified empirically -- it puts every daemon session permanently in (B), so
everything the daemon writes commits promptly instead of waiting out a
three-minute timer it would rarely survive.

Note the panel is deliberately left on this run's colour; restoring would have
overwritten the state being measured, and the boot reading is the measurement.
--- END ORIGINAL --------------------------------------------------------------

RESULT, `no-arm` (2026-07-28): **the hypothesis is FALSIFIED, and that turns
this probe into a MATCHED PAIR -- the cleanest evidence in the series.**

Magenta was written with NO arming reconnect and held the same 8 s. The panel
BOOTED TO BLUE: magenta never reached flash, and the `arm` run's blue was still
there.

    run       reconnect first?   hold   booted
    arm       YES                8 s    BLUE  (its own colour -- committed)
    no-arm    NO                 8 s    BLUE  (magenta LOST -- never committed)

Same probe, same hold, same panel, one variable. So:

  * the UNASSISTED commit is genuinely slow -- it is NOT <= 8 s;
  * condition (B) really does ARM the commit, now shown against its own matched
    control rather than against the ladder run days apart;
  * the (A) ladder was NOT measuring the wrong thing. The worry that prompted
    this sequence -- that a reconnect reads the ACTIVE MODE while only a power
    cycle reads flash, so the ladder might have measured display takeover rather
    than commit -- is a real distinction, but it does not apply: if the commit
    were fast and only takeover slow, magenta would have booted.

Added after the operator observed that the (A) ladder may have measured the
wrong thing entirely. Every rung of that ladder asked its question with a
RECONNECT, but a reconnect reads the ACTIVE MODE, not flash -- and G7/G8 showed
those are different states. If a noise GIF was still the active mode with the
colour merely painted over it, each rung was measuring "has the colour taken
over as the active mode", not "has the colour committed". Only a power cycle
reads flash directly. `no-arm` therefore repeats `arm` with the arming reconnect
REMOVED: if magenta boots after only 8 s unassisted, the unassisted commit is
fast and (A)'s 100-180 s bracket is a takeover time, not a commit time.
"""

import asyncio
import sys

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

BLUE = (0, 80, 255)  # `arm`: unmistakably not G7's green, nor the earlier orange
MAGENTA = (255, 0, 200)  # `no-arm`: must differ from BLUE too, since `arm` left blue in flash

# Each sequence writes a colour the CURRENT flash state is not. Reusing a colour
# already in flash makes reversion and survival the same picture -- the confound
# that invalidated two dwell trials on 2026-07-28.
SEQUENCE_COLOURS = {"arm": BLUE, "no-arm": MAGENTA}
HOLD_SECONDS = 8.0  # far too short for an ordinary commit -- that is the point
BLE_GAP_SECONDS = 6.0
WATCH_SECONDS = 10.0
SETTLE_SECONDS = 2.0

SEQUENCES = {
    "arm": "reconnect FIRST, then write BLUE, hold 8s, disconnect -- you power-cycle",
    "no-arm": "NO reconnect: write MAGENTA, hold 8s, disconnect -- you power-cycle",
}


def print_usage() -> None:
    print("usage: python probes/probe_p19_g8_commit_arming.py <arm|no-arm>", flush=True)
    print("", flush=True)
    print("Runs exactly ONE sequence. The argument is mandatory.", flush=True)
    for key, description in SEQUENCES.items():
        print(f"    {key:5s} {description}", flush=True)


def select_sequence(argv: list[str]) -> str:
    """Validated before any BLE contact, so a typo cannot burn a panel session."""
    if not argv:
        print("error: a sequence name is required.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    if len(argv) > 1:
        print(f"error: expected exactly one sequence name, got {len(argv)}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    if argv[0] not in SEQUENCES:
        print(f"error: unrecognized sequence {argv[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    return argv[0]


def print_visual_script(sequence: str) -> None:
    """EVERY visual of the run, in order, printed before any BLE contact."""
    armed = sequence == "arm"
    colour_name = "BLUE" if armed else "MAGENTA"
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER ============================================", flush=True)
    print("  0. BEFORE: whatever is on the panel now. Not a measurement.", flush=True)
    if armed:
        print("  1. A ~6s gap while the link drops and comes back. This reconnect is the", flush=True)
        print("     WHOLE POINT -- it is condition (B), and it happens BEFORE the write.", flush=True)
    else:
        print("  1. NO reconnect. This session connects once and stays connected, so", flush=True)
        print("     condition (B) is deliberately NOT satisfied. What the power cycle", flush=True)
        print("     shows is the UNASSISTED commit speed, read straight from flash.", flush=True)
    print(f"  2. {colour_name} fills the panel, held {HOLD_SECONDS:.0f}s -- far too short to commit by", flush=True)
    print("     ordinary dwell, which is what makes this run a discriminator.", flush=True)
    print("  3. The link drops. WATCH #1: does the colour stay, or does it revert?", flush=True)
    print("  4. The probe EXITS leaving the panel as it is. Nothing is restored:", flush=True)
    print("     restoring would overwrite the state being measured.", flush=True)
    print("  5. YOU: pull the panel's power, plug it back in, report the BOOT colour.", flush=True)
    if armed:
        print("       BOOTS BLUE -> committed in ~8s: a prior reconnect ARMS the commit.", flush=True)
        print("       BOOTS ANYTHING ELSE -> it never committed; (B) is display-only.", flush=True)
    else:
        print(f"       BOOTS MAGENTA -> the UNASSISTED commit is <= {HOLD_SECONDS:.0f}s, so the", flush=True)
        print("           100-180s (A) ladder measured display-mode TAKEOVER, not the flash", flush=True)
        print("           commit -- a reconnect cannot read flash, only a power cycle can.", flush=True)
        print("       BOOTS BLUE -> magenta never committed; flash still holds the `arm` run's", flush=True)
        print("           blue, and (A) really is slow when unassisted.", flush=True)
    print("============================================================================", flush=True)
    print("", flush=True)


async def main(sequence: str) -> None:
    print(f"sequence: {sequence} -- {SEQUENCES[sequence]}", flush=True)
    print_visual_script(sequence)

    print("connecting ...", flush=True)
    client = IDotMatrixClient(SCREEN, mac_address=ADDRESS)
    await client.connect()
    try:
        if sequence == "arm":
            print("\n=== STEP 1: disconnect/reconnect -- arming condition (B)", flush=True)
            await client.disconnect()
            await asyncio.sleep(BLE_GAP_SECONDS)
            await client.connect()
            await asyncio.sleep(SETTLE_SECONDS)
            snapshot = client.snapshot()
            print(f"    transport: {snapshot}", flush=True)
            if not snapshot.is_connected:
                print("    RECONNECT FAILED -- run is void, nothing can be concluded.", flush=True)
                return
        else:
            print("\n=== STEP 1 SKIPPED: no-arm -- this session has NOT reconnected.", flush=True)
            print("    Condition (B) is deliberately NOT satisfied, so what the power", flush=True)
            print("    cycle shows is the UNASSISTED commit speed -- read directly from", flush=True)
            print("    flash, which a reconnect-based test cannot do.", flush=True)

        print(f"\n=== STEP 2: write BLUE {BLUE}, hold {HOLD_SECONDS:.0f}s", flush=True)
        await client.color.show(BLUE)
        await asyncio.sleep(HOLD_SECONDS)

        print("\n=== STEP 3: disconnecting -- WATCH #1: does BLUE stay?", flush=True)
    finally:
        await client.disconnect()

    await asyncio.sleep(WATCH_SECONDS)
    print("\n=== NOW: PULL THE PANEL'S POWER, plug it back in, report the BOOT colour.", flush=True)
    print("    BOOTS BLUE  -> a prior reconnect ARMS the flash commit.", flush=True)
    print("    BOOTS GREEN -> (B) governs the display only; blue never committed.", flush=True)
    print("(panel deliberately left as-is -- restoring would overwrite the measurement)", flush=True)


asyncio.run(main(select_sequence(sys.argv[1:])))
