"""P3 -- graffiti byte-4 leftovers: ERASE hypothesis + values 5-7 (PROBE_PLAN.md).

Byte 4 of the graffiti header (protocol/graffiti.py's DiyImageMoveType) is
verified for 0 (plain draw), 1 (HORIZONTAL_MIRROR), 2 (VERTICAL_MIRROR). Value
4 (enum: ERASE) was tested once on a BLACK background and "drew plainly" --
but black can't distinguish "erased" (nothing rendered) from "drew black"
(the erase color happens to match the background), so that result is
inconclusive. This probe repeats the test on a non-black background and adds
the remaining unmapped values 5, 6, 7.

The public builder (graffiti.build_set_pixels) validates move_type to
(0, 1, 2) and raises for 4-7, so this probe hand-builds the raw command via a
local build_raw_graffiti() that replicates build_set_pixels's wire format
exactly, with only byte 4 overridden. Sent through client.graffiti._send
(established pattern, see probe_graffiti_byte3_final.py) since the public
set_pixels() would reject these move_type values before anything reaches the
wire.

Phases: A background (dark blue) / B draw white 2x2 (b4=0) / C same coords,
b4=4 -- ERASE TEST / D b4=5 single pixel / E b4=6 single pixel / F b4=7
single pixel / G cleanup. A response listener captures acks throughout --
graffiti accepts are silent, but rejections nack as [5,0,5,2,0], so an empty
trace after a phase means accepted (or silently swallowed), and a captured
(5,2)-shaped ack means nacked.

RESULT (2026-07-25, reference 32x32 panel, operator-narrated, dark-blue
background):

The byte-4 map is now COMPLETE -- only values 1 and 2 carry firmware semantics;
0 and 3-7 all draw plain. Graffiti stayed ack-silent throughout (only the
frame-entry background carried an ack); every drawing phase reported no acks,
i.e. no [5,0,5,2,0] nack for any byte-4 value.

  - byte4=0 (PHASE B): the white 2x2 block drew at (10,10)-(11,11) on the blue
    field and stayed. Plain draw, as the map already had it.
  - byte4=4 (PHASE C, ERASE TEST, same coords/color): NOTHING changed -- the
    white pixels stayed WHITE. They did not go black, and did not return to the
    dark-blue background. The ERASE hypothesis is FALSIFIED: on a non-black
    field, byte4=4 is a plain (no-op) re-draw, not an erase. CAVEAT recorded
    honestly: re-sending the SAME color over already-lit pixels makes "plain
    draw" and "no-op" indistinguishable by design, so this phase alone cannot
    tell those two apart -- but combined with the 2026-07-21 observation of
    byte4=4 drawing normally on black, and with 5/6/7 below, plain-draw is the
    parsimonious reading.
  - byte4=5 (PHASE D): the yellow pixel rendered at its own coords (5,20), no
    mirrored copies anywhere, no nack.
  - byte4=6 (PHASE E): the magenta pixel rendered at (20,5), no copies, no nack.
  - byte4=7 (PHASE F): the cyan pixel rendered at (26,17), no copies, no nack.

CONCLUSION: graffiti header byte 4 is fully mapped -- 1 = HORIZONTAL_MIRROR and
2 = VERTICAL_MIRROR are the only values with firmware effect; 0/3/4/5/6/7 all
draw plain (accepted silently, no mirror, no erase, no motion). The APK's
DiyImageMoveType enum names (OVERALL_MOVEMENT, ERASE) describe APP-SIDE paint-
tool behavior, not firmware behavior. P3 CLOSED.
"""

import asyncio
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
W = H = 32

DARK_BLUE = (0, 0, 96)
WHITE = (255, 255, 255)
YELLOW = (255, 255, 0)
MAGENTA = (255, 0, 255)
CYAN = (0, 255, 255)

DRAW_BLOCK = [(10, 10), (11, 10), (10, 11), (11, 11)]

_HEADER_SIZE = 8


def build_raw_graffiti(color: tuple[int, int, int], xys: list[tuple[int, int]], byte4: int) -> bytearray:
    """Hand-built graffiti command for byte-4 values the public builder
    refuses. graffiti.build_set_pixels validates move_type to (0, 1, 2) and
    raises ValueError for anything else -- this probe needs 4, 5, 6, 7, so it
    replicates that function's wire format byte-for-byte (header layout and
    zero-initialized, fully-overwritten coordinate section; see
    pyidotmatrix/protocol/graffiti.py), overriding only byte 4.
    """
    red, green, blue = color
    size = _HEADER_SIZE + 2 * len(xys)
    payload = bytearray(
        [
            size % 256,   # length LSB
            size // 256,  # length MSB (0 or 1)
            5,            # graffiti mode
            1,            # byte 3 -- the only value the device draws for
            byte4,        # byte 4 under test (4-7 unmapped)
            red,
            green,
            blue,
        ]
        + [0] * (size - _HEADER_SIZE)
    )
    for i, (x, y) in enumerate(xys):
        payload[_HEADER_SIZE + 2 * i] = x
        payload[_HEADER_SIZE + 2 * i + 1] = y
    return payload


async def countdown(phase: str, watch_for: str, n: int = 10) -> None:
    print(f"\n=== {phase} in {n}s -- WATCH FOR: {watch_for}", flush=True)
    for i in range(n, 0, -1):
        print(f"  {i} ...", flush=True)
        await asyncio.sleep(1)


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        acks: list[tuple[float, str]] = []
        client.add_response_listener(lambda ack: acks.append((time.perf_counter(), repr(ack))))

        def report_acks(label: str) -> None:
            if acks:
                print(f"  {label}: {len(acks)} ack(s) captured:", flush=True)
                for t, r in acks:
                    print(f"    [{t:.2f}s] {r}", flush=True)
                acks.clear()
            else:
                print(f"  {label}: no acks captured (silent accept, or silently swallowed)", flush=True)

        await countdown("PHASE A (background)", "uniform DARK BLUE fill, no other color")
        await client.display.show_frame(bytes(DARK_BLUE) * (W * H))
        report_acks("A")
        await asyncio.sleep(8)

        await countdown(
            "PHASE B (draw, byte4=0)",
            "white 2x2 block at (10,10)-(11,11) on the blue background",
        )
        await client.graffiti._send(build_raw_graffiti(WHITE, DRAW_BLOCK, 0))
        report_acks("B")
        await asyncio.sleep(8)

        await countdown(
            "PHASE C (ERASE TEST, byte4=4, same coords/color)",
            "do the white pixels turn BLACK, return to DARK BLUE, or stay WHITE?",
        )
        await client.graffiti._send(build_raw_graffiti(WHITE, DRAW_BLOCK, 4))
        report_acks("C")
        await asyncio.sleep(10)

        await countdown(
            "PHASE D (byte4=5, single yellow pixel)",
            "does a pixel render at (5,20)? anywhere else too (mirror combo)? nack?",
        )
        await client.graffiti._send(build_raw_graffiti(YELLOW, [(5, 20)], 5))
        report_acks("D")
        await asyncio.sleep(10)

        await countdown(
            "PHASE E (byte4=6, single magenta pixel)",
            "does a pixel render at (20,5)? anywhere else too? nack?",
        )
        await client.graffiti._send(build_raw_graffiti(MAGENTA, [(20, 5)], 6))
        report_acks("E")
        await asyncio.sleep(10)

        await countdown(
            "PHASE F (byte4=7, single cyan pixel)",
            "does a pixel render at (26,17)? anywhere else too? nack?",
        )
        await client.graffiti._send(build_raw_graffiti(CYAN, [(26, 17)], 7))
        report_acks("F")
        await asyncio.sleep(10)

        print("\ncleanup: clock restored.", flush=True)
        await client.clock.show()


asyncio.run(main())
