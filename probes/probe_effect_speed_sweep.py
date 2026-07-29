"""P1-(c) run 3 -- five-point speed sweep of effect byte 5, at both length bytes,
with the panel labelling its own phases via the scoreboard.

WHY THIS PROBE EXISTS
---------------------
Two prior runs disagree, and this sweep exists to replace argument with a curve.

Run 1 (probes/probe_effect_length_byte.py, 2026-07-26): 4 phases, no repeats, no
reset between phases. Operator-reported pace ranked P2 > P1 > P4 > P3 -- i.e. at
BOTH declared lengths, speed 5 appeared FASTER than speed 100:

    phase  length byte      speed  ack   pace
    P2     0x0d malformed   5      NONE  fastest
    P1     0x0d malformed   100    ack   2nd
    P4     0x1c correct     5      ack   3rd
    P3     0x1c correct     100    ack   slowest

That contradicts the 2026-07-25 group A run (probes/probe_p1_followups.py), where
the SAME correct-length frame at 100 / 5 / 100 read "smooth -> slow -> smooth".
On group A's strength, effect.speed was promoted KNOWN_BROKEN -> VERIFIED in
capabilities.py. That promotion currently rests on contested evidence.

Run 2 (probes/probe_effect_length_byte2.py, same night, 7 phases with clock
resets between them) produced exactly one clean fact: ALL THREE frames declaring
0x1c were acked, and ALL FOUR declaring 0x0d drew NO ACK WHATSOEVER -- including
phase E, a well-formed 13-byte 2-color control frame that was not malformed at
all. In run 1 a 0x0d frame HAD acked once. Whether the 0x0d frames render
anything is still unknown, because run 2's operator ratings were never collected.

So this sweep answers three things at once:

  (a) Does the pace actually track byte 5 MONOTONICALLY across five points at the
      valid length 0x1c? A five-point curve is far harder to misread than any of
      the pairwise comparisons both prior runs were built on.
  (b) Does the 0x0d ack silence reproduce across all five speeds?
  (c) Do the 0x0d phases render AT ALL? The scoreboard phase boundary makes this
      obvious: if the effect never appears, the scoreboard simply stays on screen
      through the whole watch window.

DESIGN
------
The operator cannot see stdout, so THE PANEL LABELS ITS OWN PHASES. Each phase
opens with scoreboard.show(speed, declared_length) held for 4 s: count1 is the
speed, count2 is the declared length as a DECIMAL number (28 or 13, not 0x1c /
0x0d). That single display is both the phase label and the phase boundary.

The speed set (5/25/50/75/100) and the length set (13/28) are DISJOINT, so the
scoreboard reads unambiguously even if count1/count2 render in the opposite
orientation to what we expect -- a 13 or 28 can only be the length, a 5/25/50/75
can only be the speed, and 100 pairs with neither length value.

Every frame is a hand-built bytearray sent through client.effect._send with
verify=False. Deliberately NOT routed through protocol.effect.build_show: that
builder now emits the CORRECT length byte, and the point here is to put the
malformed shape back on the wire. verify=False keeps a hand-built frame from
raising CommandRejectedError mid-run; acks still arrive through the response
listener, which fires regardless of verification.

28 bytes go on the wire in EVERY phase. Only byte 0 (declared length) and byte 5
(speed) change across the whole run; the palette, style and color count are
pinned, so nothing else can explain a difference.

METHOD
------
Device reset (common.reset, 04 00 03 80 -- VERIFIED non-destructive, used live
2026-07-18 to clear a stuck state) to start from a known state, settle, clock
baseline, clear acks. Nothing in the `experimental` namespace is touched and
delete_device_data is never called. Each phase is wrapped so one failure cannot
end the run. Cleanup: clock.

READOUT
-------
  * Pace rises monotonically 5 -> 100 at length 28  => byte 5 is a SPEED, higher
    = faster. Group A stands and run 1 was an artifact.
  * Pace falls monotonically 5 -> 100 at length 28  => byte 5 is a DELAY /
    interval, higher = slower, and capabilities.py's effect.speed needs
    correcting.
  * No pace change across all five speeds at length 28 => the field is INERT and
    the VERIFIED promotion must be reverted.
  * Scoreboard persists through the length-13 watch windows => those frames are
    dropped outright, never executed, and every pace reading ever taken from a
    0x0d frame is VOID.
  * Effect renders at length 13 despite ZERO acks => the device acts on commands
    it does not acknowledge. New and important; record prominently.

USAGE
-----
    python probes/probe_effect_speed_sweep.py          # both lengths, 10 phases
    python probes/probe_effect_speed_sweep.py 28       # 0x1c only, 5 phases
    python probes/probe_effect_speed_sweep.py 0x0d     # 0x0d only, 5 phases

Decimal and hex spellings are both accepted. Selecting one length re-runs that
half in isolation; nothing else about a phase changes.

RESULT (2026-07-26): CLEAN. All 10 phases RENDERED -- the effect appeared in
every watch window, at BOTH declared lengths, so no frame was dropped. Pace rose
MONOTONICALLY 5 -> 100 at BOTH declared lengths. Byte 5 is a SPEED, higher =
faster: CONFIRMED. The 2026-07-25 group A run reproduces, and capabilities.py's
effect.speed VERIFIED promotion stands. Run 1's inverted reading (speed 5
apparently faster than 100) is attributed to its lack of clock resets between
phases: its phases 2-4 landed on an already-running effect instead of entering
the mode fresh.

RETRACTION: run 2's headline finding -- "all four 0x0d frames drew no ack
whatsoever" -- is WITHDRAWN. It was an instrumentation bug in the probe, not a
device behavior. All ten effect frames here DID ack. The device's reply takes
roughly 4.3 s; run 2 called report_acks immediately after the send, read an
empty list, and then cleared that list at the phase boundary before the reply
ever arrived. This probe surfaced the bug because the scoreboard command gave an
independent timing reference. Any conclusion anywhere resting on 0x0d ack
silence is void.

ADDENDUM (2026-07-27): a later run of this probe hit one unreproduced visual
FREEZE at a single effect-to-scoreboard phase transition. Every other
transition in that run -- five or more of them -- was seamless, and the
scoreboard acks bracketing the event were spaced evenly at 14.44-14.61 s apart,
which is the normal per-phase cycle time and shows no stall on the BLE link
itself. Logged as an observed-but-unreproduced transient (capabilities.py,
display.visual_transients) rather than a protocol finding; it does not change
the speed-field conclusion above.
"""

import asyncio
import sys
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

# The app's 7-color palette from the 2026-07-25 capture, in wire order -- held
# identical across all phases so it can never explain a difference. All 7 are
# sent in every phase here; only bytes 0 and 5 of the header ever vary.
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

# Outer loop. 0x1c = 28 = 7 header + 21 color bytes, as the vendor app sends it;
# 0x0d = 13 = our lab-era `6 + len(colors)`, wrong for a 7-color frame.
DECLARED_LENGTHS = (0x1C, 0x0D)

# Inner loop. Disjoint from {13, 28} on purpose -- see DESIGN.
SPEEDS = (5, 25, 50, 75, 100)

LABEL_SECONDS = 4   # scoreboard hold: phase label AND phase boundary
WATCH_SECONDS = 10


def select_declared_lengths(argv: list[str]) -> tuple[int, ...]:
    """Which half (or halves) of the sweep to run, from the command line.

    No argument keeps the original behavior: both lengths, 0x1c then 0x0d. One
    argument runs just that length, in decimal or hex spelling. Parsing happens
    before the device is touched, so a typo cannot half-run a sweep.
    """
    if not argv:
        return DECLARED_LENGTHS

    accepted = "no argument (both), " + ", ".join(f"{n} / 0x{n:02x}" for n in DECLARED_LENGTHS)
    if len(argv) > 1:
        print(f"expected at most one length argument; accepted: {accepted}", flush=True)
        raise SystemExit(2)

    try:
        requested = int(argv[0], 0)  # base 0 takes both "28" and "0x1c"
    except ValueError:
        requested = -1
    if requested not in DECLARED_LENGTHS:
        print(f"unrecognized length {argv[0]!r}; accepted: {accepted}", flush=True)
        raise SystemExit(2)
    return (requested,)


def build_frame(declared_length: int, speed: int) -> bytearray:
    """The captured 7-color effect frame with both variables exposed.

    28 bytes on the wire regardless of what byte 0 declares; every byte except 0
    (declared length) and 5 (speed) is pinned to the capture.
    """
    return bytearray([declared_length, 0x00, 0x03, 0x02, APP_EFFECT_STYLE, speed, 0x07]) + APP_EFFECT_COLORS


async def main(declared_lengths: tuple[int, ...]) -> None:
    selected = ", ".join(f"{n} (0x{n:02x})" for n in declared_lengths)
    print(f"declared lengths selected: {selected} -- {len(declared_lengths) * len(SPEEDS)} phases", flush=True)
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
                # Run 2 saw every 0x0d frame go unacked while run 1 saw one ack.
                # Our standing rule is "acks confirm receipt, not effect"; an
                # effect WITHOUT an ack would be the new and opposite thing, so
                # silence is recorded loudly rather than passed over.
                print(f"  {label}: *** ZERO ACKS CAPTURED *** -- record this, it is a result", flush=True)

        # Known-state entry: reset (04 00 03 80, non-destructive), settle, then
        # the clock baseline. Nothing from the experimental namespace is used.
        try:
            print("resetting device to a known state ...", flush=True)
            await client.device.reset()
            await asyncio.sleep(4)
            await client.clock.show()
            await asyncio.sleep(3)
            acks.clear()
            print("baseline: clock. acks cleared.", flush=True)
        except Exception as ex:
            print(f"  reset/clock baseline FAILED: {ex!r}", flush=True)

        for declared_length in declared_lengths:
            for speed in SPEEDS:
                label = f"len {declared_length} (0x{declared_length:02x}) / speed {speed}"
                try:
                    # Scoreboard = the phase label the operator can actually see,
                    # and the boundary that makes a non-rendering effect obvious:
                    # if the panel still shows these two numbers 10 s later, the
                    # frame was never executed.
                    print(f"\n=== PHASE {label} -- scoreboard {speed} | {declared_length}", flush=True)
                    await client.scoreboard.show(speed, declared_length)
                    await asyncio.sleep(LABEL_SECONDS)

                    frame = build_frame(declared_length, speed)
                    print(f"  sending: {frame.hex(' ')}", flush=True)
                    await client.effect._send(frame, verify=False)
                    report_acks(f"{label} (expect 05 00 03 02 01)")

                    print(f"  WATCH ({WATCH_SECONDS}s): rate the pace ABSOLUTELY (1=crawling, 5=racing);"
                          f" if the scoreboard is STILL on screen, the frame did not render", flush=True)
                    await asyncio.sleep(WATCH_SECONDS)
                except Exception as ex:
                    print(f"  {label} FAILED: {ex!r}", flush=True)

        print("\nverdict to record (absolute ratings, not comparisons):", flush=True)
        print("  pace rises 5->100 at len 28  => byte 5 is a SPEED; group A stands, run 1 was"
              " the artifact.", flush=True)
        print("  pace falls 5->100 at len 28  => byte 5 is a DELAY/interval; capabilities.py"
              " needs correcting.", flush=True)
        print("  no pace change at len 28     => field is INERT; revert the VERIFIED promotion.", flush=True)
        print("  scoreboard persists at len 13 => those frames are dropped, never executed; all 0x0d", flush=True)
        print("                                  pace readings ever taken are void.", flush=True)
        print("  effect renders at len 13 with zero acks => device acts on unacknowledged commands.", flush=True)
        print("                                            New and important -- record prominently.", flush=True)

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main(select_declared_lengths(sys.argv[1:])))
