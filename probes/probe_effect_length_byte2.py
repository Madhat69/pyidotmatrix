"""P1-(c) run 2 -- ABA re-test of the effect speed byte, plus the 2-color
palette-truncation control that run 1 never had.

WHY THIS PROBE EXISTS
---------------------
Run 1 (probes/probe_effect_length_byte.py, 2026-07-26) asked whether the
malformed length byte hid the speed field. Four phases, no repeats, no reset
between them. Operator-reported pace, ranked P2 > P1 > P4 > P3:

    phase  length byte      speed  ack   pace
    P2     0x0d malformed   5      NONE  fastest
    P1     0x0d malformed   100    ack   2nd
    P4     0x1c correct     5      ack   3rd
    P3     0x1c correct     100    ack   slowest

Two readings follow from that, and they do not agree.

(1) Within BOTH length bytes, speed 5 ran FASTER than speed 100 -- the same
    direction twice. The malformed frame responded to the speed field just as
    the correct one did, so the hypothesis that the length byte GATES the speed
    field is FALSIFIED.
(2) But this contradicts the 2026-07-25 group A run (probes/probe_p1_followups.py),
    where the SAME correct frame at 100 / 5 / 100 was reported "smooth -> slow
    -> smooth". Same bytes, opposite direction. On the strength of group A,
    effect.speed was promoted KNOWN_BROKEN -> VERIFIED in capabilities.py. That
    promotion now rests on contested evidence and may need demoting.

Three design faults in run 1 that this probe fixes:

  * NO CONDITION WAS EVER REPEATED, so drift (thermal, connection, a mode that
    settles over time) is indistinguishable from a response to the bytes. Fixed
    here with ABA within each length byte: A1/B1/A2 and C1/D1/C2. If the return
    leg does not match its own opening leg, the pair is void.
  * DELIVERY CONTEXT VARIED. Only run 1's first phase was sent from the clock;
    the other three landed on an already-running effect. Group A's phases were
    fresh mode entries. Fixed here by returning to the clock between EVERY
    phase, which also gives the operator an unambiguous visual phase boundary
    (they cannot see stdout).
  * THE OPERATOR JUDGED EACH PHASE AGAINST A 10-SECOND MEMORY OF THE PREVIOUS
    ONE. A single transcription slip in that relative chain initially inverted
    the whole verdict. Fixed here by asking for an ABSOLUTE pace rating per
    phase (see the note above the phase table).

UNTESTED CONFOUNDER: PALETTE TRUNCATION
---------------------------------------
At length byte 0x0d the device may be honoring the declared length and
rendering only TWO colors -- 13 bytes - 7 header = 6 bytes = 2 RGB triples --
out of the 7 we send. A 2-color cycle completes faster than a 7-color one at an
IDENTICAL frame interval. That alone would explain both malformed phases
outrunning both correct phases, with nothing whatsoever to do with speed.

Phase E is the control run 1 lacked: a genuinely WELL-FORMED 2-color frame,
[0d 00 03 02 00 64 02] + the first two palette colors, whose declared 0x0d is
the true total length of its 13-byte body. Compared against C1 (malformed,
same declared length, same speed 100) it separates "13 means 2 colors" from
"13 means malformed".

ACKS ARE A FIRST-CLASS RESULT HERE
----------------------------------
Run 1's phase P2 drew NO ack while the other three each got [05 00 03 02 01],
spaced exactly one phase-cycle apart -- so it was not a listener race -- and
yet the operator still saw the panel change. Our standing rule is "acks confirm
receipt, not effect"; an EFFECT WITHOUT AN ACK would be the new and opposite
thing, a visible state change the device never acknowledged. Whether that
silence reproduces is therefore recorded per phase, and a zero-ack phase is
printed explicitly rather than passed over.

METHOD
------
Device reset (common.reset, 04 00 03 80 -- VERIFIED non-destructive, used live
2026-07-18 to clear a stuck state) to start from a known state, settle, clock
baseline, clear acks. Nothing in the `experimental` namespace is touched and
delete_device_data is never called.

Every frame is a hand-built bytearray sent through client.effect._send with
verify=False. Deliberately NOT routed through protocol.effect.build_show: that
builder now emits the CORRECT length byte, and half the point of this probe is
to put the malformed shape back on the wire. verify=False keeps a hand-built
frame from raising CommandRejectedError mid-run; acks are read off the response
listener instead, which fires regardless of verification.

Palette, style and every other byte are pinned across phases 1-6; only the
length byte and the speed byte vary, and each phase names which. Phase E also
varies the color count -- that is its entire purpose and it is compared only
against C1.

READOUT
-------
  * A1 ~= A2 and B1 SLOWER than both  => 2026-07-25 group A reproduces. The
    speed field is real with 100 = fast, and run 1's reading was the artifact.
    capabilities.py's VERIFIED stands.
  * A1 ~= A2 and B1 FASTER than both  => run 1 reproduces. The field is
    INVERTED from our assumption -- it is a delay/interval, not a speed -- and
    capabilities.py's effect.speed entry needs correcting.
  * A1 != A2                          => the run drifted. BOTH pairs are void
    and NO verdict may be recorded from this run, whatever B1 and D1 did.
  * E ~= C1                           => palette truncation CONFIRMED. The
    device honors the declared length and renders 2 colors, so every
    malformed-vs-correct pace difference is a cycle-length artifact, not speed.
  * E != C1                           => the device is NOT truncating on the
    declared length; the malformed frame renders all 7 colors, and the pace
    difference between length bytes needs another explanation.

Timing per phase: 10 s countdown, 10 s watch, ~4 s clock before the next
countdown. Each phase is wrapped so one failure cannot end the run. Cleanup:
clock.

RESULT (2026-07-26): superseded and PARTIALLY RETRACTED. All three phases
declaring the correct length 0x1c (A1, B1, A2) acked normally; all four
phases declaring the malformed length 0x0d (C1, D1, C2, and the well-formed
2-color control E) drew ZERO ACKS in this run's report. That "0x0d never
acks" finding was published in capabilities.py and PROBE_PLAN.md history and
is now WITHDRAWN as of probes/probe_effect_speed_sweep.py (run 3, same
night): the silence was an instrumentation bug, not a device behavior --
report_acks was called immediately after each send and the ack list was
cleared at the next phase boundary, before the device's ~4.3 s reply for an
effect command had arrived. Run 3 confirmed every declared length acks. The
absolute pace ratings this run was designed to collect (to separate a
malformed-length-byte-hides-speed hypothesis from a delivery-context
confound) were not usefully recorded and are superseded by run 3's
five-point sweep, which found byte 5 is a genuine speed field, higher =
faster, at both declared lengths -- see capabilities.py's effect.speed
entry for the resolved account.
"""

import asyncio
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

# The app's 7-color palette from the 2026-07-25 capture, in wire order -- held
# identical across all phases so it can never explain a difference. Phase E
# uses the first two entries only, which is its declared purpose.
APP_EFFECT_COLORS = bytes.fromhex(
    "7f0000"  # dark red
    "7f5100"  # amber
    "7f7f00"  # olive
    "007f00"  # green
    "00007f"  # blue
    "7f007f"  # purple
    "7f7f7f"  # grey
)
APP_EFFECT_STYLE = 0

LENGTH_MALFORMED = 0x0D  # our lab-era `6 + len(colors)` for 7 colors -- wrong
LENGTH_CORRECT = 0x1C    # 7 header + 21 color bytes, as the vendor app sends it
LENGTH_TWO_COLORS = 0x0D  # 7 header + 6 color bytes -- genuinely correct here

SPEED_FAST = 100  # 0x64, the app's fast dial position
SPEED_SLOW = 5

COUNTDOWN_SECONDS = 10
WATCH_SECONDS = 10
CLOCK_SECONDS = 4  # clock hold between phases: equalizes delivery context


def build_seven_color_frame(length_byte: int, speed: int) -> bytearray:
    """The captured 7-color effect frame with both variables exposed.

    Every byte except 0 (length) and 5 (speed) is pinned to the capture, so any
    two of phases 1-6 differ in exactly the bytes their labels name.
    """
    return bytearray([length_byte, 0x00, 0x03, 0x02, APP_EFFECT_STYLE, speed, 0x07]) + APP_EFFECT_COLORS


def build_two_color_frame(speed: int) -> bytearray:
    """The well-formed 2-color control (phase E).

    Declared length 0x0d is the TRUE total length of this 13-byte body (7
    header + 2*3 color bytes), unlike the malformed phases where the same 0x0d
    understates a 28-byte body. Colors are the first two of the shared palette,
    so E differs from C1 only in how many colors actually reach the wire.
    """
    return bytearray([LENGTH_TWO_COLORS, 0x00, 0x03, 0x02, APP_EFFECT_STYLE, speed, 0x02]) + APP_EFFECT_COLORS[:6]


async def countdown(phase: str, watch_for: str, n: int = COUNTDOWN_SECONDS) -> None:
    print(f"\n=== {phase} in {n}s -- WATCH FOR: {watch_for}", flush=True)
    for i in range(n, 0, -1):
        print(f"  {i} ...", flush=True)
        await asyncio.sleep(1)


# Each phase: (label, frame, what the operator should watch for).
#
# The operator reports an ABSOLUTE pace rating per phase -- e.g. a 1-5 scale, or
# "roughly N cycles in the 10s window" -- NOT "faster/slower than the last one".
# The relative chain is exactly what failed in run 1: one mis-transcribed
# comparison inverted the entire verdict, and a relative chain has no way to
# detect that. Absolute ratings are independently checkable after the fact.
PHASES = (
    ("A1 CORRECT 0x1c, 7 colors, speed 100",
     build_seven_color_frame(LENGTH_CORRECT, SPEED_FAST),
     "rate the pace ABSOLUTELY (1=crawling, 5=racing). This is the A-leg opener"),
    ("B1 CORRECT 0x1c, 7 colors, speed 5",
     build_seven_color_frame(LENGTH_CORRECT, SPEED_SLOW),
     "rate the pace ABSOLUTELY -- do NOT compare to A1, just rate it"),
    ("A2 CORRECT 0x1c, 7 colors, speed 100 (ABA return)",
     build_seven_color_frame(LENGTH_CORRECT, SPEED_FAST),
     "rate ABSOLUTELY -- must match A1's rating or the A/B pair is void (drift)"),
    ("C1 MALFORMED 0x0d, 7 colors sent, speed 100",
     build_seven_color_frame(LENGTH_MALFORMED, SPEED_FAST),
     "rate ABSOLUTELY, and COUNT THE COLORS if you can -- 7 or 2?"),
    ("D1 MALFORMED 0x0d, 7 colors sent, speed 5",
     build_seven_color_frame(LENGTH_MALFORMED, SPEED_SLOW),
     "rate ABSOLUTELY, and count the colors again -- 7 or 2?"),
    ("C2 MALFORMED 0x0d, 7 colors sent, speed 100 (ABA return)",
     build_seven_color_frame(LENGTH_MALFORMED, SPEED_FAST),
     "rate ABSOLUTELY -- must match C1's rating or the C/D pair is void (drift)"),
    ("E WELL-FORMED 2-color control, 0x0d, speed 100",
     build_two_color_frame(SPEED_FAST),
     "rate ABSOLUTELY. Same as C1 => the device truncates the palette to 2 colors"),
)


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        acks: list[tuple[float, str]] = []
        unsubscribe = client.add_response_listener(lambda ack: acks.append((time.perf_counter(), repr(ack))))

        def report_acks(label: str) -> None:
            if acks:
                print(f"  {label}: {len(acks)} ack(s) captured:", flush=True)
                for t, r in acks:
                    print(f"    [{t:.2f}s] {r}", flush=True)
                acks.clear()
            else:
                # Run 1's P2 was silent yet visibly changed the panel. "Acks
                # confirm receipt, not effect" is our standing rule; an effect
                # WITHOUT an ack would be new, so silence is recorded loudly.
                print(f"  {label}: *** ZERO ACKS CAPTURED *** -- record this, it is a result", flush=True)

        # Known-state entry: reset (04 00 03 80, non-destructive), settle, then
        # the clock baseline. Nothing from the experimental namespace is used.
        try:
            print("resetting device to a known state ...", flush=True)
            await client.common.reset()
            await asyncio.sleep(4)
            await client.clock.show()
            await asyncio.sleep(3)
            acks.clear()
            print("baseline: clock. acks cleared.", flush=True)
        except Exception as ex:
            print(f"  reset/clock baseline FAILED: {ex!r}", flush=True)

        for label, frame, watch_for in PHASES:
            try:
                await countdown(f"PHASE {label}", watch_for)
                print(f"  sending: {frame.hex(' ')}", flush=True)
                await client.effect._send(frame, verify=False)
                report_acks(f"{label} (expect 05 00 03 02 01)")
                print(f"  WATCH ({WATCH_SECONDS}s): {watch_for}", flush=True)
                await asyncio.sleep(WATCH_SECONDS)
            except Exception as ex:
                print(f"  {label} FAILED: {ex!r}", flush=True)

            # Clock between EVERY phase: makes the next effect command a fresh
            # mode entry (as group A's were, unlike run 1's phases 2-4) and
            # marks the phase boundary for an operator who cannot see stdout.
            try:
                print(f"  -> clock for {CLOCK_SECONDS}s (phase boundary)", flush=True)
                await client.clock.show()
                await asyncio.sleep(CLOCK_SECONDS)
                acks.clear()
            except Exception as ex:
                print(f"  clock reset after {label} FAILED: {ex!r}", flush=True)

        print("\nverdict to record (absolute ratings, not comparisons):", flush=True)
        print("  A1 != A2            => run drifted; BOTH pairs void, no verdict.", flush=True)
        print("  A1 ~= A2, B1 slower => group A reproduces; 100=fast; run 1 was the artifact.", flush=True)
        print("  A1 ~= A2, B1 faster => run 1 reproduces; byte 5 is a DELAY, not a speed;", flush=True)
        print("                         capabilities.py effect.speed needs correcting.", flush=True)
        print("  E ~= C1             => palette truncation confirmed; length-byte pace", flush=True)
        print("                         differences are cycle-length, not speed.", flush=True)
        print("  E != C1             => no truncation; malformed frame renders all 7 colors.", flush=True)

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
