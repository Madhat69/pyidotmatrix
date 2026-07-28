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
    python probes/probe_p19_g8_commit_arming.py arm

The argument is mandatory. Runtime ~45 s, plus your power cycle.

RESULT (2026-07-28): **CONFIRMED -- a prior reconnect ARMS THE FLASH COMMIT.**

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
"""

import asyncio
import sys

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

BLUE = (0, 80, 255)  # unmistakably not G7's green, nor the earlier orange
HOLD_SECONDS = 8.0  # far too short for an ordinary commit -- that is the point
BLE_GAP_SECONDS = 6.0
WATCH_SECONDS = 10.0
SETTLE_SECONDS = 2.0

SEQUENCES = {"arm": "reconnect, write BLUE, hold 8s, disconnect -- then you power-cycle"}


def print_usage() -> None:
    print("usage: python probes/probe_p19_g8_commit_arming.py arm", flush=True)
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


def print_visual_script() -> None:
    """EVERY visual of the run, in order, printed before any BLE contact."""
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER ============================================", flush=True)
    print("  0. BEFORE: whatever is on the panel now. Not a measurement.", flush=True)
    print("  1. A ~6s gap while the link drops and comes back. This reconnect is the", flush=True)
    print("     WHOLE POINT -- it is condition (B), and it happens BEFORE the write.", flush=True)
    print(f"  2. BLUE fills the panel and is held {HOLD_SECONDS:.0f}s -- far too short to commit", flush=True)
    print("     by ordinary dwell, which is what makes this run a discriminator.", flush=True)
    print("  3. The link drops. WATCH #1: does BLUE stay, or does the panel revert?", flush=True)
    print("     (Reverting would show GREEN -- the current flash state, from G7.)", flush=True)
    print("  4. The probe EXITS leaving the panel as it is. Nothing is restored:", flush=True)
    print("     restoring would overwrite the state being measured.", flush=True)
    print("  5. YOU: pull the panel's power, plug it back in, and report the BOOT colour.", flush=True)
    print("       BOOTS BLUE  -> blue committed in ~8s: a prior reconnect ARMS the", flush=True)
    print("                      flash commit.", flush=True)
    print("       BOOTS GREEN -> blue never committed; flash still holds G7's green, so", flush=True)
    print("                      condition (B) governs the DISPLAY only.", flush=True)
    print("============================================================================", flush=True)
    print("", flush=True)


async def main(sequence: str) -> None:
    print(f"sequence: {sequence} -- {SEQUENCES[sequence]}", flush=True)
    print_visual_script()

    print("connecting ...", flush=True)
    client = IDotMatrixClient(SCREEN, mac_address=ADDRESS)
    await client.connect()
    try:
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
