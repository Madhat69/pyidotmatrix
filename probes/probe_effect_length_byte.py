"""P1-(c) -- isolate the effect command's LENGTH BYTE as the cause of the
2026-07-21 "effect speed is inert" record.

What we know as of 2026-07-25. probe_p1_followups.py group A replayed the
vendor app's own effect frame at speed 100 / 5 / 100 and the operator saw
SMOOTH / visibly SLOW / SMOOTH -- byte 5 is the real speed field and the device
honours it. But three earlier probes (probe_effect_speed{,2}.py,
probe_effect_set_speed.py) swept the same byte through OUR builder and saw
nothing at all. Something about our frames hid the field.

The prime suspect is byte 0. Our lab-era build_show wrote `6 + len(colors)` =
0x0d for a 7-color command; the app writes 0x1c = 28 = the true total frame
length (7 header + 3*7 color bytes). A device that parses the header by that
length would see a 13-byte command, find the speed field outside the frame it
believes it was handed, and still have enough of the payload to render
*something* -- which is exactly what we observed: the effect appeared, the
speed never moved.

Suspect, not conclusion. Group A also changed the style (0, vs 2 and 4), the
palette (the app's 7 colors), and the delivery (a complete command rather than
a mid-animation tweak). Any of those could carry the difference. So this probe
changes ONE BYTE and nothing else:

    (i)  OLD  [0d 00 03 02 00 SPEED 07] + the same 21 color bytes
    (ii) NEW  [1c 00 03 02 00 SPEED 07] + the same 21 color bytes

and runs each at both speeds: old@100, old@5, correct@100, correct@5.

READOUT:
  * old@5 looks the SAME as old@100, while correct@5 is visibly slower than
    correct@100  => THE LENGTH BYTE WAS THE CULPRIT. The 2026-07-21 record is
    fully explained, and protocol/effect.py's fix is the whole remedy.
  * old@5 slows down too  => the length byte never mattered; the device does
    not gate on it, and whatever made the old probes inert lives in the style,
    the palette, or the mid-animation delivery. That reopens the question.
  * correct@5 does NOT slow  => tonight's group A result did not reproduce;
    stop and re-examine before trusting either reading.

Both frames are hand-built bytearrays sent through client.effect._send with
verify=False. Deliberately NOT routed through protocol.effect.build_show: that
builder now emits the correct length byte, and the point of this probe is to
put the OLD malformed shape back on the wire one last time. verify=False keeps
a hand-built frame from raising CommandRejectedError mid-run; acks are read off
the response listener instead, which fires regardless of verification. Expect
[05 00 03 02 01] per send -- and note whether the malformed frames ack at all,
which is itself a data point (2026-07-21 says they did).

Baseline clock, then four phases, each a 10s countdown + 10s watch, each
wrapped so one failure cannot end the run. Cleanup: clock.

RESULT (2026-07-26): INCONCLUSIVE, superseded. Operator-reported pace ranked
P2 > P1 > P4 > P3 -- i.e. at BOTH declared lengths, speed 5 appeared FASTER
than speed 100, the opposite of the 2026-07-25 group A reading. P2 (old
length, speed 5) drew no ack in this run's report; P1/P3/P4 each acked
[05 00 03 02 01]. Taken at face value this would mean either the length byte
inverts the speed field or the field is not a speed at all -- but see
probes/probe_effect_length_byte2.py and probes/probe_effect_speed_sweep.py:
the design fault run 3 identified is that this run's four phases ran back to
back with NO clock reset between them, so phases 2-4 each landed on an
already-running effect instead of a fresh mode entry, which is now the
leading explanation for the inverted pace reading. Run 3's five-point sweep
(with a clock reset before every phase) found byte 5 responds monotonically
as a real speed field, higher = faster, at both declared lengths, and that
result is what stands in capabilities.py (effect.speed). This run's own
readings should be treated as void rather than reused.
"""

import asyncio
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

# The app's 7-color palette from the 2026-07-25 capture, in wire order -- held
# identical across all four phases so it can never explain a difference.
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

LENGTH_OLD = 0x0D  # our lab-era `6 + len(colors)` for 7 colors -- malformed
LENGTH_CORRECT = 0x1C  # 7 header + 21 color bytes, as the vendor app sends it

SPEED_FAST = 100  # 0x64, the app's fast dial position
SPEED_SLOW = 5

WATCH_SECONDS = 10


def build_frame(length_byte: int, speed: int) -> bytearray:
    """The captured effect frame with both variables exposed.

    Every byte except 0 (length) and 5 (speed) is pinned to the capture, so a
    phase pair differing only in the length byte is a true one-variable test.
    """
    return bytearray([length_byte, 0x00, 0x03, 0x02, APP_EFFECT_STYLE, speed, 0x07]) + APP_EFFECT_COLORS


async def countdown(phase: str, watch_for: str, n: int = 10) -> None:
    print(f"\n=== {phase} in {n}s -- WATCH FOR: {watch_for}", flush=True)
    for i in range(n, 0, -1):
        print(f"  {i} ...", flush=True)
        await asyncio.sleep(1)


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
                print(f"  {label}: NO acks captured (itself a result for the malformed frames)", flush=True)

        # Start from the clock so phase 1's effect is unmistakably new.
        try:
            await client.clock.show()
            await asyncio.sleep(3)
            acks.clear()
        except Exception as ex:
            print(f"  clock baseline FAILED: {ex!r}", flush=True)

        # Order matters: the two OLD phases run back to back, so the operator
        # judges "did it slow?" against the immediately preceding frame rather
        # than against a memory of a different length byte.
        phases = (
            (
                "P1 OLD length 0x0d",
                LENGTH_OLD,
                SPEED_FAST,
                "effect starts -- fix this pace in mind, it is the OLD-frame baseline",
            ),
            (
                "P2 OLD length 0x0d",
                LENGTH_OLD,
                SPEED_SLOW,
                "SAME pace as P1, or slower? SAME => the malformed length byte hid the speed field",
            ),
            ("P3 CORRECT length 0x1c", LENGTH_CORRECT, SPEED_FAST, "fast again -- the CORRECT-frame baseline"),
            (
                "P4 CORRECT length 0x1c",
                LENGTH_CORRECT,
                SPEED_SLOW,
                "visibly SLOW vs P3? (this must reproduce 2026-07-25 group A for the run to count)",
            ),
        )

        for label, length_byte, speed, watch_for in phases:
            try:
                await countdown(f"PHASE {label}, SPEED={speed}", watch_for)
                frame = build_frame(length_byte, speed)
                print(f"  sending: {frame.hex(' ')}", flush=True)
                await client.effect._send(frame, verify=False)
                report_acks(f"{label} (expect 05 00 03 02 01)")
                print(f"  WATCH ({WATCH_SECONDS}s): {watch_for}", flush=True)
                await asyncio.sleep(WATCH_SECONDS)
            except Exception as ex:
                print(f"  {label} FAILED: {ex!r}", flush=True)

        print("\nverdict to record: did P2 differ from P1? did P4 differ from P3?", flush=True)
        print("  P1==P2 and P3!=P4  => the length byte was the culprit.", flush=True)
        print("  P1!=P2             => the length byte never mattered; look elsewhere.", flush=True)

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
