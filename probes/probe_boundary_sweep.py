"""P13 -- non-destructive validation-boundary sweep (PROBE_PLAN.md).

Where the SDK's own validation is STRICTER than the wire, we cannot learn the
device's real boundary through the public API -- the builder raises (countdown
minutes>59) or silently clamps (scoreboard >999) before anything is sent. This
probe drives the actual firmware limits by hand-building RAW frames that
replicate each builder's wire layout exactly, then sends them through the
established raw path (client.graffiti._send with verify=False -- fire-and-forget,
so no pending ack-wait is opened; see probes/probe_graffiti_byte4_erase.py). A
response listener captures every fa03 so an out-of-range value's DeviceAck
(accepted=False, a nack) is visible per phase; an empty trace means the device
accepted (or silently swallowed) the frame.

Raw layouts (derived from pyidotmatrix/protocol/*.py):
  - brightness  [5, 0, 4, 128, value]              (common.build_set_brightness)
  - countdown   [7, 0, 8, 128, mode, min, sec]     (countdown.build_set_mode)
  - scoreboard  [8, 0, 10, 128, lo1, hi1, lo2, hi2] little-endian per score
                                                    (scoreboard.build_show)
  - graffiti    [len_lo, len_hi, 5, 1, move, r,g,b] + (x,y) pairs
                                                    (graffiti.build_set_pixels)

Phases (each self-contained; a failure in one is caught and the run continues):
  A. Brightness ladder via RAW frames: 0, 1, 4 (below the SDK's 5 floor -- the
     P7 'brightness floor' question), 101, 255 (above the 100 ceiling), then
     restore 60 via the normal API. A white backdrop is shown first so any
     dim/brighten is visible. WATCH: does each dim/brighten/no-op? which nack?
  B. Fullscreen RGB extremes via the NORMAL API: (1,1,1), (254,254,254),
     (255,0,255), (0,0,0), 6s each. WATCH: does (1,1,1) light at all? is
     (0,0,0) 'off-looking'?
  C. Countdown 60:00. The SDK rejects minutes=60 (build_set_mode raises for
     >59), so a valid 59:59 is shown via the normal API for contrast, then the
     RAW frame [7,0,8,128,1,60,0] is sent. WATCH: nack, clamp to a 59:59-style
     value, or run at 60:00?
  D. Scoreboard 1000. The SDK clamps to 999 (build_show never sends 1000), so a
     valid 999 is shown via the normal API for contrast, then the RAW frame
     [8,0,10,128,232,3,0,0] (count1=1000, little-endian 0x03E8) is sent. WATCH:
     nack, render 000, render 999?
  E. Graffiti batch length 256 in ONE raw oversized command: 256 coord pairs
     (rows 24-31 x cols 0-31, a full 8-row sweep so overflow is visible),
     byte4=0, one solid color. size = 8 + 2*256 = 520, so the length header is
     [8, 2]. The SDK's MAX_PIXELS_PER_COMMAND is 255, so this is one over.
     WATCH: nack ([5,0,5,2,0])? draws 255? draws 256? nothing?

Cleanup: clock restored.

RESULT (2026-07-__): pending.
"""

import asyncio
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
W = H = 32

WHITE = (255, 255, 255)
GREEN = (0, 255, 0)

_HEADER_SIZE = 8


def build_raw_graffiti(color: tuple[int, int, int], xys: list[tuple[int, int]], byte4: int) -> bytearray:
    """Hand-built graffiti command replicating graffiti.build_set_pixels's wire
    format byte-for-byte (header + zero-initialized, fully-overwritten coordinate
    section), overriding byte 4 and free of the public builder's 255-pixel cap.
    For len(xys)=256, size=520, so the length header is (8, 2) -- the MSB rolls
    to 2, which is the whole point of the overflow test."""
    red, green, blue = color
    size = _HEADER_SIZE + 2 * len(xys)
    payload = bytearray(
        [
            size % 256,   # length LSB
            size // 256,  # length MSB (2 at 256 pairs)
            5,            # graffiti mode
            1,            # byte 3 -- the only value the device draws for
            byte4,        # byte 4 (0 = plain draw)
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


def build_raw_brightness(value: int) -> bytearray:
    """common.build_set_brightness layout, without its 5..100 validation."""
    return bytearray([5, 0, 4, 128, value])


def build_raw_countdown(mode: int, minutes: int, seconds: int) -> bytearray:
    """countdown.build_set_mode layout, without its 0..59 validation."""
    return bytearray([7, 0, 8, 128, mode, minutes, seconds])


def build_raw_scoreboard(count1: int, count2: int) -> bytearray:
    """scoreboard.build_show layout: each score little-endian (LSB then MSB),
    without the builder's 0..999 clamp. 1000 = 0x03E8 -> LSB 232, MSB 3."""
    lo1, hi1 = count1 & 0xFF, (count1 >> 8) & 0xFF
    lo2, hi2 = count2 & 0xFF, (count2 >> 8) & 0xFF
    return bytearray([8, 0, 10, 128, lo1, hi1, lo2, hi2])


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

        # --- PHASE A: brightness ladder via RAW frames ---
        try:
            print("\nPHASE A setup: white fullscreen backdrop so brightness is visible.", flush=True)
            await client.color.show(WHITE)
            report_acks("A-setup(white)")
            await asyncio.sleep(3)
            for value in (0, 1, 4, 101, 255):
                try:
                    await countdown(
                        f"PHASE A brightness={value} (RAW)",
                        f"does the white panel dim/brighten/no-op at {value}? nack?",
                        n=8,
                    )
                    await client.graffiti._send(build_raw_brightness(value), verify=False)
                    report_acks(f"A brightness={value}")
                    await asyncio.sleep(4)
                except Exception as exc:  # noqa: BLE001 -- keep the ladder alive
                    print(f"  A brightness={value} FAILED: {exc!r}", flush=True)
            print("\nPHASE A restore: brightness 60 via the normal API.", flush=True)
            await client.common.set_brightness(60)
            report_acks("A restore=60")
            await asyncio.sleep(3)
        except Exception as exc:  # noqa: BLE001
            print(f"PHASE A FAILED: {exc!r}", flush=True)

        # --- PHASE B: fullscreen RGB extremes via the normal API ---
        try:
            for color, note in (
                ((1, 1, 1), "does (1,1,1) light AT ALL, or read as off?"),
                ((254, 254, 254), "near-white -- distinguishable from full white?"),
                ((255, 0, 255), "saturated magenta"),
                ((0, 0, 0), "is (0,0,0) 'off-looking' (black) vs powered-off?"),
            ):
                await countdown(f"PHASE B color={color}", note, n=6)
                await client.color.show(color)
                report_acks(f"B color={color}")
                await asyncio.sleep(6)
        except Exception as exc:  # noqa: BLE001
            print(f"PHASE B FAILED: {exc!r}", flush=True)

        # --- PHASE C: countdown 60:00 (SDK rejects; raw frame) ---
        try:
            await countdown(
                "PHASE C reference 59:59 (normal API)",
                "a valid 59:59 countdown starts running -- the contrast case",
                n=6,
            )
            await client.countdown.start(59, 59)
            report_acks("C reference 59:59")
            await asyncio.sleep(4)
            await countdown(
                "PHASE C 60:00 (RAW [7,0,8,128,1,60,0])",
                "nack? clamp to a 59:59-style value? or run at 60:00?",
            )
            await client.graffiti._send(build_raw_countdown(1, 60, 0), verify=False)
            report_acks("C raw 60:00")
            await asyncio.sleep(8)
            await client.countdown.stop()
        except Exception as exc:  # noqa: BLE001
            print(f"PHASE C FAILED: {exc!r}", flush=True)

        # --- PHASE D: scoreboard 1000 (SDK clamps; raw frame) ---
        try:
            await countdown(
                "PHASE D reference 999 (normal API)",
                "a valid 999 renders -- the contrast case",
                n=6,
            )
            await client.scoreboard.show(999, 0)
            report_acks("D reference 999")
            await asyncio.sleep(4)
            await countdown(
                "PHASE D 1000 (RAW [8,0,10,128,232,3,0,0])",
                "nack? render 000 (LSB/MSB wrap)? render 999? something else?",
            )
            await client.graffiti._send(build_raw_scoreboard(1000, 0), verify=False)
            report_acks("D raw 1000")
            await asyncio.sleep(8)
        except Exception as exc:  # noqa: BLE001
            print(f"PHASE D FAILED: {exc!r}", flush=True)

        # --- PHASE E: graffiti batch length 256 (one over the 255 cap) ---
        try:
            coords = [(x, y) for y in range(24, 32) for x in range(32)]  # 8 rows x 32 = 256
            assert len(coords) == 256
            await countdown(
                "PHASE E graffiti 256-px batch (RAW, size=520, header (8,2))",
                "nack ([5,0,5,2,0])? does a green sweep fill rows 24-31 (256)? "
                "or only 255 of them? or nothing?",
            )
            await client.graffiti._send(build_raw_graffiti(GREEN, coords, 0), verify=False)
            report_acks("E graffiti 256")
            await asyncio.sleep(10)
        except Exception as exc:  # noqa: BLE001
            print(f"PHASE E FAILED: {exc!r}", flush=True)

        print("\ncleanup: clock restored.", flush=True)
        await client.clock.show()


asyncio.run(main())
