"""P8 -- canonical geometry, color-order, and flip contract (PROBE_PLAN.md).

Proves the hardware contract behind show_frame()/set_pixels() with asymmetric
landmarks (house lesson 2026-07-21: symmetric layouts made mirroring look like
recoloring -- never again). Landmarks are chosen so every failure mode has a
distinct visual signature:

  - corner blocks TL=RED TR=GREEN BL=BLUE BR=WHITE
      -> transpose (column-major) swaps GREEN and BLUE corners
      -> BGR channel order swaps RED and BLUE corners
  - single YELLOW pixel at (8,3): BGR renders it CYAN (channel canary)
  - CYAN shallow diagonal (12,12)->(18,15): asymmetric under both mirrors
  - single MAGENTA pixel at (3,20): survives BGR unchanged (control)

Phases: A full-frame landmarks / B same landmarks via graffiti /
C flip ON + resend frame / D flip ON + graffiti at origin / E cleanup.

RESULT (2026-07-24, two identical runs, operator-narrated): CLEAN SWEEP.
  A: corners exactly as painted (TL red / TR green / BL blue / BR white);
     lone canary px YELLOW, not cyan => row-major, top-left origin, RGB order.
  B: graffiti landmarks matched frame positions and colors => graffiti shares
     the frame coordinate space exactly.
  C: flip ON => TL white / TR blue / BR red / BL green; yellow px moved to
     lower-right, magenta to upper-right => flip is a 180-DEGREE ROTATION
     (both diagonal pairs swapped), not a single-axis mirror.
  D: graffiti (0,0)..(2,0) under flip lit the bottom edge of the bottom-right
     red block -- pixel-exact match for (31,31),(30,31),(29,31) => flip
     transforms graffiti too. Commands stay in canonical unflipped space;
     the panel rotates at render (consistent with native clock, 2026-07-21).
"""

import asyncio

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
W = H = 32

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)

DIAGONAL = [(12, 12), (14, 13), (16, 14), (18, 15)]


def block(x0: int, y0: int, size: int = 4) -> list[tuple[int, int]]:
    return [(x0 + dx, y0 + dy) for dy in range(size) for dx in range(size)]


def landmark_frame() -> bytes:
    """Row-major RGB frame; the panel tells us whether that assumption holds."""
    buf = bytearray(W * H * 3)

    def put(x: int, y: int, rgb: tuple[int, int, int]) -> None:
        i = (y * W + x) * 3
        buf[i : i + 3] = bytes(rgb)

    for x, y in block(0, 0):
        put(x, y, RED)
    for x, y in block(W - 4, 0):
        put(x, y, GREEN)
    for x, y in block(0, H - 4):
        put(x, y, BLUE)
    for x, y in block(W - 4, H - 4):
        put(x, y, WHITE)
    put(8, 3, YELLOW)
    for x, y in DIAGONAL:
        put(x, y, CYAN)
    put(3, 20, MAGENTA)
    return bytes(buf)


async def countdown(phase: str, watch_for: str, n: int = 10) -> None:
    print(f"\n=== {phase} in {n}s -- WATCH FOR: {watch_for}", flush=True)
    for i in range(n, 0, -1):
        print(f"  {i} ...", flush=True)
        await asyncio.sleep(1)


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        frame = landmark_frame()

        await countdown(
            "PHASE A (full frame)",
            "corner colors clockwise from top-left; color of the lone pixel near top-left",
        )
        await client.display.show_frame(frame)
        print(
            "A: expected TL=RED TR=GREEN BL=BLUE BR=WHITE, lone YELLOW px upper-left area,\n"
            "   CYAN diagonal center, lone MAGENTA px mid-left. Narrate what differs. (12s)",
            flush=True,
        )
        await asyncio.sleep(12)

        await countdown("PHASE B (graffiti, same landmarks)", "same corners/pixel or shifted?")
        await client.display.show_frame(bytes(W * H * 3))  # black canvas
        await client.graffiti.set_pixels(RED, block(0, 0, 2))
        await client.graffiti.set_pixels(GREEN, block(W - 2, 0, 2))
        await client.graffiti.set_pixels(BLUE, block(0, H - 2, 2))
        await client.graffiti.set_pixels(WHITE, block(W - 2, H - 2, 2))
        await client.graffiti.set_pixels(YELLOW, [(8, 3)])
        print("B: 2x2 corner blocks same colors as A + lone YELLOW px. Same positions as A? (10s)", flush=True)
        await asyncio.sleep(10)

        await countdown("PHASE C (flip ON + resend frame)", "where did the RED corner go?")
        await client.common.set_screen_flipped(True)
        await client.display.show_frame(frame)
        print(
            "C: if flip=180deg rotation, RED lands bottom-right and YELLOW px lower-right area.\n"
            "   If only vertical mirror, RED lands bottom-left. Narrate. (12s)",
            flush=True,
        )
        await asyncio.sleep(12)

        await countdown("PHASE D (flip still ON, graffiti at origin)", "which corner gets 3 YELLOW px?")
        await client.graffiti.set_pixels(YELLOW, [(0, 0), (1, 0), (2, 0)])
        print("D: does graffiti (0,0) follow the flip (bottom-right) or ignore it (top-left)? (10s)", flush=True)
        await asyncio.sleep(10)

        print("\ncleanup: flip off, clock restored.", flush=True)
        await client.common.set_screen_flipped(False)
        await client.clock.show()


asyncio.run(main())
