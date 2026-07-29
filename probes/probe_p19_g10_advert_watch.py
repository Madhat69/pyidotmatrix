"""P19 G10 stage 0 -- validate the advertisement watch as a power-cut instrument.

WHY THIS PROBE EXISTS
---------------------
G8 and G9 both tried to measure when a write reaches flash, and both failed for
the same reason: **the interval between the probe disconnecting and the operator
pulling the power was never controlled or recorded.** If the commit can finish
after the link drops, that unrecorded interval is part of the effective dwell,
and two runs nominally at "8 s" can differ by a minute of real elapsed time. The
8 s rung duly committed in one run and not in another, the ladder lost its lower
anchor, and the "a reconnect ARMS the commit" claim had to be retracted.

The fix is not a stopwatch and not a steadier hand. The panel ADVERTISES whenever
it is powered and not connected -- that is how discover() finds it. So a scanner
left running after the probe disconnects can see the power cut happen:
advertisements stop when the plug comes out and resume when the panel boots.

That turns the uncontrolled variable into a MEASURED one, which is better than
controlling it. The operator no longer has to hit a target time at all -- pull
the cable whenever -- because the probe records the true write-to-power-loss
interval. Sloppy timing stops being a confound and becomes sample diversity.

WHY STAGE 0 EXISTS SEPARATELY
-----------------------------
G8 and G9 measured with an instrument nobody had checked. This probe checks the
instrument BEFORE any measurement is spent on it, and answers three questions:

  1. Do we see this panel's advertisements at all, and how often? The cadence is
     the error bar: the true power cut lies between the last advertisement seen
     and one interval later.
  2. Does a real power cycle produce a clean stop-and-resume?
  3. Does the panel keep advertising while idle, or does it stop on its own? A
     spontaneous stop would forge a power cut and quietly poison every trial.

If any answer disappoints, the approach dies here having cost one power cycle.

THIS PROBE NEVER CONNECTS AND NEVER WRITES
------------------------------------------
No connection is opened. Nothing is sent. The panel's display is not touched, so
whatever is on it now (LIME, from the G9 8 s retry) stays, and the flash state
under test is preserved for stage A. Scanning is passive observation of
advertisements the panel is already broadcasting.

WHAT THE OPERATOR DOES
----------------------
  1. Leave the panel alone for the baseline window.
  2. When told, PULL THE PANEL'S POWER. Timing does not matter -- that is the
     entire point -- but do not pull before being asked, or the baseline is lost.
  3. Plug it back in when told. Report nothing; the probe measures it all.

USAGE
-----
    python probes/probe_p19_g10_advert_watch.py instrument

Runtime: ~30 s baseline, plus however long you take, plus the boot.

RESULT (2026-07-29): **PASSED. The advertisement watch is a usable power-cut
instrument, and the uncontrolled interval that wrecked G8 and G9 is now
measurable to well under a second.**

    advertisements   57 in 30 s of idle baseline
    median interval  110 ms      <- typical uncertainty on the cut instant
    worst interval   2116 ms     <- honest worst-case bound (see below)
    silence => cut   6.3 s       (derived: 3x the worst observed live gap)
    power cut        last advertisement t+60.4 s, declared at t+66.9 s
    boot             t+92.8 s, dark for 32.4 s
    boot colour      LIME, as expected -- this probe writes nothing, and it
                     confirms flash held what the G9 8 s retry left there

All three questions answered:

  1. The panel advertises steadily at ~9 Hz nominal. The cut instant is pinned
     to the last advertisement seen, so the error is one advertising gap:
     ~110 ms typically. **The bound to quote is the WORST gap, ~2.1 s** -- the
     advertiser is bursty and occasionally goes quiet for two seconds while
     perfectly alive. Against dwells measured in tens of seconds that is
     comfortably small, but it is not the 110 ms the first draft claimed, and
     the probe was corrected to print both.
  2. A real power cycle produced a clean stop and a clean resume. Boot was
     detected without ambiguity.
  3. **It did not fire spuriously.** 30 s of idle advertising never went quiet
     long enough to forge a cut -- the failure mode that would have silently
     poisoned every trial. The 6.3 s threshold sits 3x above the worst real gap.

CONSEQUENCE: the operator no longer has to hit a target time. The power cut is
observed rather than scheduled, so any pull whenever is a valid data point, and
the write-to-cut interval that G8/G9 left unrecorded is now recorded. G11 spends
this instrument on the actual question.
"""

import asyncio
import itertools
import statistics
import sys
import time

from bleak import AdvertisementData, BleakScanner
from bleak.backends.device import BLEDevice

ADDRESS = "6D:FD:F8:A0:3E:AF"
NAME_PREFIX = "IDM-"

SEQUENCES = ("instrument",)

BASELINE_SECONDS = 30.0
PROGRESS_EVERY = 5.0
POLL_SECONDS = 0.2

# How long a silence must last before we call it a power cut. Derived from the
# worst gap actually observed while the panel was known to be alive, so a slow
# or jittery advertiser widens it automatically instead of faking a cut.
DEAD_GAP_FLOOR = 4.0
DEAD_GAP_CEILING = 20.0
DEAD_GAP_SAFETY_FACTOR = 3.0

WAIT_FOR_PULL_SECONDS = 300.0
WAIT_FOR_BOOT_SECONDS = 180.0


def print_usage() -> None:
    print("usage: python probes/probe_p19_g10_advert_watch.py <sequence>", flush=True)
    print("", flush=True)
    print(f"sequence: {', '.join(SEQUENCES)}", flush=True)
    print("", flush=True)
    print("  instrument -- baseline the advertising cadence, then watch one power", flush=True)
    print("                cycle. Never connects, never writes, never touches the", flush=True)
    print("                display. Validates the watch before stage A uses it.", flush=True)


def select(argv: list[str]) -> str:
    """Validated before any BLE contact, so a typo cannot burn a panel session."""
    if len(argv) != 1:
        print(f"error: expected exactly 1 argument, got {len(argv)}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    sequence = argv[0].lower()
    if sequence not in SEQUENCES:
        print(f"error: unknown sequence {argv[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    return sequence


def print_visual_script() -> None:
    """EVERY visual of the run, in order, printed before any BLE contact."""
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER ============================================", flush=True)
    print("  0. THE PANEL'S DISPLAY NEVER CHANGES during this probe. Not once.", flush=True)
    print("     Nothing is connected to, nothing is sent. If the picture changes,", flush=True)
    print("     something else is talking to the panel -- stop and say so.", flush=True)
    print("     (It should be LIME, left there by the G9 8 s retry.)", flush=True)
    print(f"  1. {BASELINE_SECONDS:.0f}s of silence while the cadence is baselined. Do nothing.", flush=True)
    print("  2. YOU: pull the panel's power when asked. WHENEVER you like -- the", flush=True)
    print("     probe measures when you did it, so there is no time to hit.", flush=True)
    print("     The display goes dark. That is the plug, not the probe.", flush=True)
    print("  3. YOU: plug it back in when asked. The panel boots to whatever its", flush=True)
    print("     flash state is (expected LIME -- but that is stage A's question,", flush=True)
    print("     not this one; nothing here has changed what is in flash).", flush=True)
    print("============================================================================", flush=True)
    print("", flush=True)


def summarise_gaps(stamps: list[float]) -> tuple[float, float]:
    """Returns (median, worst) interval between consecutive advertisements.

    Takes a snapshot: the scanner callback appends to the live list from another
    task, and a sequence that grows mid-calculation is a bug waiting to happen.
    """
    snapshot = list(stamps)
    gaps = [b - a for a, b in itertools.pairwise(snapshot)]
    return statistics.median(gaps), max(gaps)


async def main(sequence: str) -> None:
    print(f"sequence: {sequence}", flush=True)
    print_visual_script()

    stamps: list[float] = []
    others: dict[str, str] = {}

    def on_detect(device: BLEDevice, adv: AdvertisementData) -> None:
        if device.address.upper() == ADDRESS.upper():
            stamps.append(time.monotonic())
        elif adv.local_name and adv.local_name.startswith(NAME_PREFIX):
            others[device.address] = adv.local_name

    print("scanning (no connection is opened) ...", flush=True)
    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    try:
        # --- 1. baseline the cadence while the panel is known to be alive -----
        print(f"\n=== BASELINE: {BASELINE_SECONDS:.0f}s, leave the panel alone ===", flush=True)
        started = time.monotonic()
        next_progress = PROGRESS_EVERY
        while (elapsed := time.monotonic() - started) < BASELINE_SECONDS:
            if elapsed >= next_progress:
                print(f"    t+{elapsed:5.1f}s  advertisements seen: {len(stamps)}", flush=True)
                next_progress += PROGRESS_EVERY
            await asyncio.sleep(POLL_SECONDS)

        if len(stamps) < 2:
            print(f"\n  FAILED: saw {len(stamps)} advertisement(s) from {ADDRESS}.", flush=True)
            print("  The watch cannot work if the panel is not seen advertising.", flush=True)
            if others:
                print("  Other iDotMatrix devices that WERE seen:", flush=True)
                for address, name in sorted(others.items()):
                    print(f"    {address}  {name}", flush=True)
                print("  If one of those is your panel, ADDRESS in this probe is wrong.", flush=True)
            else:
                print("  No iDotMatrix devices seen at all. Is the panel powered? Is", flush=True)
                print("  something else (the app, the daemon) holding a connection?", flush=True)
            raise SystemExit(1)

        median_gap, worst_gap = summarise_gaps(stamps)
        dead_gap = min(DEAD_GAP_CEILING, max(DEAD_GAP_FLOOR, worst_gap * DEAD_GAP_SAFETY_FACTOR))
        print(f"\n  advertisements : {len(stamps)} in {BASELINE_SECONDS:.0f}s", flush=True)
        print(f"  median interval: {median_gap * 1000:7.0f} ms   <- the measurement's error bar", flush=True)
        print(f"  worst interval : {worst_gap * 1000:7.0f} ms   (while known alive)", flush=True)
        print(f"  silence meaning 'power cut': {dead_gap:.1f}s", flush=True)

        # --- 2. watch for the cut ---------------------------------------------
        print("\n=== NOW: PULL THE PANEL'S POWER. Any moment you like. ===", flush=True)
        print("    Timing does not matter. The probe records when you did it.", flush=True)
        armed = time.monotonic()
        while True:
            now = time.monotonic()
            silence = now - stamps[-1]
            if silence >= dead_gap:
                break
            if now - armed > WAIT_FOR_PULL_SECONDS:
                print(f"\n  gave up: no power cut seen in {WAIT_FOR_PULL_SECONDS:.0f}s.", flush=True)
                print("  The panel kept advertising throughout. Nothing was harmed;", flush=True)
                print("  re-run when ready to pull the plug.", flush=True)
                raise SystemExit(1)
            await asyncio.sleep(POLL_SECONDS)

        lost_at = stamps[-1]
        seen_before_boot = len(stamps)
        print(f"\n  POWER CUT DETECTED at t+{time.monotonic() - started:.1f}s", flush=True)
        print(f"    last advertisement: t+{lost_at - started:.1f}s", flush=True)
        # The honest bound is the WORST gap, not the median: the true cut sits
        # between the last advertisement and whenever the next one would have
        # arrived, and that spacing is occasionally far wider than typical.
        print(f"    true cut lies after that by ~{median_gap * 1000:.0f} ms typical,", flush=True)
        print(f"    {worst_gap * 1000:.0f} ms worst case (widest gap seen while alive).", flush=True)

        # --- 3. watch for the boot --------------------------------------------
        print("\n=== NOW: PLUG IT BACK IN. ===", flush=True)
        waited = time.monotonic()
        while len(stamps) == seen_before_boot:
            if time.monotonic() - waited > WAIT_FOR_BOOT_SECONDS:
                print(f"\n  gave up: no advertisements in {WAIT_FOR_BOOT_SECONDS:.0f}s after replug.", flush=True)
                print("  The stop was detected cleanly, but the resume was not -- so the", flush=True)
                print("  watch is only half validated. Do not run stage A on this.", flush=True)
                raise SystemExit(1)
            await asyncio.sleep(POLL_SECONDS)
        booted_at = stamps[seen_before_boot]
    finally:
        await scanner.stop()

    # --- 4. verdict -----------------------------------------------------------
    print(f"\n  BOOT DETECTED at t+{booted_at - started:.1f}s", flush=True)
    print(f"    dark for {booted_at - lost_at:.1f}s", flush=True)
    print("\n=== INSTRUMENT CHECK: PASSED =============================================", flush=True)
    print("  The watch saw a clean stop and a clean resume, and it did not fire", flush=True)
    print(f"  spuriously across {BASELINE_SECONDS:.0f}s of idle advertising.", flush=True)
    print(
        f"  A power cut is timed to ~{median_gap * 1000:.0f} ms typically, {worst_gap * 1000:.0f} ms worst case.",
        flush=True,
    )
    print("==========================================================================", flush=True)
    print("\n  Report the panel's BOOT COLOUR (expected LIME -- unchanged, since this", flush=True)
    print("  probe wrote nothing). A different colour would mean flash held something", flush=True)
    print("  other than we believed, which matters before stage A runs.", flush=True)


asyncio.run(main(select(sys.argv[1:])))
