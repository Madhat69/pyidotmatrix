"""P7-follow-up -- does a PAUSED COUNTDOWN hijack the chronograph? (unlabelled)

WHY THIS PROBE EXISTS
---------------------
2026-07-20 reported that native timer modes share device state: a paused
countdown appeared to HIJACK a subsequent `chronograph.start()`, resuming the
countdown instead of starting a stopwatch. P7's rerun (2026-07-27,
probes/probe_p7_odds_and_ends.py) did NOT reproduce it -- the operator saw an
independent stopwatch counting UP from zero.

But P7 narrated itself on the panel with SCOREBOARD LABELS between phases, and
its own author flagged in advance that those labels are native-mode commands
which could clear the shared timer state, making them "suspect #1 if the hijack
fails to reproduce". It failed to reproduce. So the independence result has
never been separated from its own instrumentation.

That caution was vindicated on 2026-07-28 by P19 G3: on-panel labels between
phases of a clock-style sweep silently switched modes out from under the test
and manufactured TWO false capability-table entries that stood for a day. The
same hazard, demonstrated. This probe therefore sends NO labels at all.

WHAT IT DOES
------------
Three commands, nothing else, no labels, no reset, no scoreboard, no text:

  1. `countdown.start(5, 0)`  -- a 5-minute countdown, so a resumed countdown is
     unmistakable (it counts DOWN from ~04:5x and is nowhere near zero).
  2. `countdown.pause()`      -- freeze it. The frozen value is the evidence:
     whatever it reads is what a hijacked chronograph would continue FROM.
  3. `chronograph.start()`    -- THE QUESTION.

WHAT THE ANSWER LOOKS LIKE
--------------------------
  INDEPENDENT -- the display resets to 00:00 and counts UP. The chronograph is
                 its own timer; P7's result stands and 2026-07-20's hijack
                 report was the contaminated one.
  HIJACKED    -- the display continues from the frozen countdown value (counting
                 DOWN, or resuming from that number). The shared-state model is
                 real and P7's independence result was an artifact of its own
                 scoreboard labels.

The operator reads three numbers off the panel, which is the whole job. The
panel clock has NO SECONDS, but the countdown and chronograph faces DO show
their own digits -- those are what to read, not the clock.

SAFETY
------
Sends only countdown and chronograph mode commands plus a final `clock.show()`.
No reset, no brightness, no eco, no flip, no RTC write, no GIF, no experimental
namespace, nothing near the password or UART surface.

USAGE
-----
    python probes/probe_p7b_timer_state_unlabelled.py hijack

The argument is mandatory. Runtime ~1.5 min.

RESULT (2026-07-28): **INDEPENDENT. The hijack does not reproduce, and this run
removes the last reason to doubt that.**

Operator readings, in order:
  (a) the countdown ticked DOWN as expected;
  (b) it froze at **04:48** when paused;
  (c) `chronograph.start()` showed **00:12**, INCREMENTING throughout the 12 s
      window -- i.e. it reset to zero and counted UP freely. 00:12 over a 12 s
      watch is exactly a stopwatch started from zero.

The chronograph did NOT continue from 04:48, and it was not frozen either. It is
its own timer.

WHAT THIS CLOSES. P7 (2026-07-27) already reported independence, but P7 narrated
itself with scoreboard labels between phases and its own author had flagged those
labels as "suspect #1 if the hijack fails to reproduce" -- so its result could
never be separated from its instrumentation, especially after P19 G3 proved on
2026-07-28 that on-panel labels really do switch modes mid-test and had already
manufactured two false capability entries. This run sent THREE COMMANDS AND
NOTHING ELSE: no label, no scoreboard, no text, no reset. Same answer.

So the 2026-07-20 report that "native timer modes share device state -- a paused
countdown hijacks chronograph commands" is FALSIFIED on this firmware, not merely
unreproduced. Two independent runs now agree, and the instrumentation objection
to the first one has been eliminated by construction.

Scope, stated honestly: this tests ONE ordering -- countdown start, pause, then
chronograph start. It does not test the reverse (chronograph paused, then
countdown started), nor countdown.restart() after a chronograph, nor any
scoreboard interaction. "Countdown and chronograph are independent timers" is
supported for this sequence; a broader claim about all native timer modes sharing
no state is NOT established here.
"""

import asyncio
import sys

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

COUNTDOWN_MINUTES = 5
RUN_SECONDS = 12.0  # let it visibly tick down before pausing
WATCH_SECONDS = 12.0
SETTLE_SECONDS = 2.0

SEQUENCES = {
    "hijack": "countdown -> pause -> chronograph.start, with NO labels between phases",
}


def print_usage() -> None:
    print("usage: python probes/probe_p7b_timer_state_unlabelled.py <sequence>", flush=True)
    print("", flush=True)
    print("Runs exactly ONE sequence. The argument is mandatory.", flush=True)
    for key, description in SEQUENCES.items():
        print(f"    {key:8s} {description}", flush=True)


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
    print("  0. BEFORE: whatever is on the panel now stays up while the client connects.", flush=True)
    print("     It is not a measurement. NO label, scoreboard or text appears at ANY", flush=True)
    print("     point in this run -- that is deliberate and is the whole point.", flush=True)
    print(f"  1. COUNTDOWN ({RUN_SECONDS:.0f}s): a {COUNTDOWN_MINUTES}:00 countdown starts and ticks DOWN.", flush=True)
    print("     Confirm it is counting down.", flush=True)
    print(f"  2. PAUSED ({WATCH_SECONDS:.0f}s): it should FREEZE. **WRITE DOWN THE FROZEN", flush=True)
    print("     NUMBER** -- around 04:4x. That number is the evidence for step 3.", flush=True)
    print(f"  3. CHRONOGRAPH ({WATCH_SECONDS:.0f}s): THE QUESTION. Report which you see:", flush=True)
    print("       INDEPENDENT -- display resets to 00:00 and counts UP.", flush=True)
    print("       HIJACKED    -- display continues from the frozen number you wrote", flush=True)
    print("                      down (counting down, or resuming from it).", flush=True)
    print("  4. CLEANUP: the ordinary clock face. Not a result.", flush=True)
    print("  Read the COUNTDOWN/CHRONOGRAPH digits, not the clock -- the clock face has", flush=True)
    print("  no seconds and is not part of this measurement.", flush=True)
    print("============================================================================", flush=True)
    print("", flush=True)


async def main(sequence: str) -> None:
    print(f"sequence: {sequence} -- {SEQUENCES[sequence]}", flush=True)
    print_visual_script()

    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, SCREEN) as client:
        print(f"=== STEP 1: countdown.start({COUNTDOWN_MINUTES}, 0) -- watch it tick DOWN", flush=True)
        await client.countdown.start(COUNTDOWN_MINUTES, 0)
        await asyncio.sleep(RUN_SECONDS)

        print("\n=== STEP 2: countdown.pause() -- WRITE DOWN THE FROZEN NUMBER", flush=True)
        await client.countdown.pause()
        await asyncio.sleep(WATCH_SECONDS)

        print("\n=== STEP 3: chronograph.start() -- THE QUESTION", flush=True)
        print("    INDEPENDENT -- resets to 00:00 and counts UP", flush=True)
        print("    HIJACKED    -- continues from the frozen countdown number", flush=True)
        await client.chronograph.start()
        await asyncio.sleep(WATCH_SECONDS)

        print("\n--- cleanup ---", flush=True)
        await client.chronograph.reset()
        await asyncio.sleep(SETTLE_SECONDS)
        await client.clock.show()
        print("panel restored to the clock face.", flush=True)

    print("disconnected.", flush=True)
    print("\nReport: (a) did it tick down, (b) the frozen number, (c) INDEPENDENT or HIJACKED.", flush=True)


asyncio.run(main(select_sequence(sys.argv[1:])))
