"""P1 follow-ups -- the two mechanisms tonight's vendor-app HCI capture exposed:
effect speed via byte 5 (byte-identical app frame), and a music-sync rhythm
LEVEL STREAM that our music_sync module does not implement at all.

PHASE GROUP A -- effect speed, byte-identical replay
---------------------------------------------------
Our earlier speed probes (probe_effect_speed.py, probe_effect_speed2.py,
probe_effect_set_speed.py) all reported "no visible change" and byte 5 was
written off as inert. Those probes used OUR builder with OUR style/colors. The
capture shows the app's own frame differs from protocol.effect.build_show's
output in a way that could matter:

    app:  [0x1C, 0x00, 0x03, 0x02, 0x00, SPEED, 0x07] + 7 RGB triples
    ours: [6 + len(colors), 0, 3, 2, style, speed, len(colors)] + triples

For 7 colors ours emits byte0 = 13, the app emits 0x1C = 28 -- i.e. the app's
length byte counts TOTAL FRAME BYTES (7 + 21), not 6 + colorCount. If the
firmware gates the speed field on a well-formed length byte, every one of our
speed tests was malformed in exactly the way that would hide the effect. The
app also used style 0 and a specific 7-color palette, and the operator watched
the dial visibly change the animation pace ON THIS PANEL with SPEED 0x5A then
0x64. So this phase replays the captured frame byte-for-byte and varies only
byte 5. This is the decisive retest: if the pace does not move here, byte 5 is
dead on this firmware and the app's dial does something else entirely.

Sent raw via client.effect._send (the established probe pattern, see
probe_graffiti_byte4_erase.py) because build_show cannot emit the app's length
byte. verify=False on every send so a hand-built frame can never raise
CommandRejectedError mid-run and kill the phase -- acks are read off the
response listener instead, which fires for every ack regardless of verification
(transport/ble.py _handle_notification fans out to listeners after resolving
any pending wait). Expect [05 00 03 02 01] per send: device ack, effect family.

PHASE GROUP B -- music-sync rhythm level stream
-----------------------------------------------
Fully new mechanism. protocol/music_sync.py's build_send_image_rhythm
([6,0,0,2,value,1]) is a different, and by the capture's evidence wrong,
command -- the app never sends it. What the app actually streams is:

    [0x21, 0x00, 0x01, 0x02, 0x00] + 16 level bytes

at roughly 10 Hz, UNACKED (fire-and-forget, no ack observed for any stream
frame). Device-observed level range is 0x00-0x0D; the app computes 8 band
levels and mirrors them into a 16-byte palindrome, so the panel renders a
symmetric spectrum. Its companion frame, sent once when the music screen opens,
is a 6-byte mic-type command:

    [0x06, 0x00, 0x0B, 0x80, 0x01, 0x64]

which is our build_set_mic_type([6,0,11,128,mic_type]) plus a trailing 0x64 --
so that builder is short by a byte as well. Both are hand-built here.

The open question B answers: does the stream render on its own, or does the
panel need the mic-type frame first as a mode entry? B1 streams cold from the
clock, B2 sends the mic frame and repeats the identical stream, B3 pins every
band at full so the geometry (columns? rows? how many?) can be read off a
static frame.

Phases: A1 speed=100 / A2 speed=5 / A3 speed=100 / clock / B1 cold stream /
B2 mic frame + stream / B3 static full-blast / cleanup. Each phase is wrapped
so one failure does not end the run.

RESULT (2026-07-__): pending.
"""

import asyncio
import math
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

# --- PHASE GROUP A: the captured frame, reproduced exactly -------------------

# The app's 7-color palette from the capture, in wire order.
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

SPEED_FAST = 100  # 0x64, the app's second dial position
SPEED_SLOW = 5

# --- PHASE GROUP B: the captured rhythm stream ------------------------------

RHYTHM_HEADER = bytes([0x21, 0x00, 0x01, 0x02, 0x00])
MIC_TYPE_FRAME = bytearray([0x06, 0x00, 0x0B, 0x80, 0x01, 0x64])

BAND_COUNT = 8          # bands the app computes before mirroring
LEVEL_BYTES = 16        # bands mirrored into a palindrome
LEVEL_MAX = 13          # 0x0D, the highest level observed from the device
STREAM_HZ = 10
STREAM_SECONDS = 12


def build_app_effect_frame(speed: int) -> bytearray:
    """The captured app effect frame, byte-identical except byte 5 (speed).

    Byte 0 is the app's 0x1C -- total frame length (7 header + 21 color bytes),
    NOT protocol.effect.build_show's 6 + colorCount. That difference is the
    point of this probe, so the constant is hardcoded rather than recomputed
    through our builder's formula.
    """
    return bytearray([0x1C, 0x00, 0x03, 0x02, APP_EFFECT_STYLE, speed, 0x07]) + APP_EFFECT_COLORS


def build_rhythm_frame(levels: list[int]) -> bytearray:
    """Wraps 16 already-mirrored level bytes in the captured stream header."""
    return bytearray(RHYTHM_HEADER) + bytes(levels)


def mirrored_levels(tick: int) -> list[int]:
    """8 animated band levels mirrored into the app's 16-byte palindrome.

    band i at tick t = int(6.5 + 6.5*sin(t/3 + i*0.8)), clamped to 0..13, so
    the bands sweep the full observed range out of phase with each other -- a
    travelling wave is far easier to see on the panel than random noise.
    """
    bands = [
        max(0, min(LEVEL_MAX, int(6.5 + 6.5 * math.sin(tick / 3 + i * 0.8))))
        for i in range(BAND_COUNT)
    ]
    return bands + bands[::-1]


async def countdown(phase: str, watch_for: str, n: int = 10) -> None:
    print(f"\n=== {phase} in {n}s -- WATCH FOR: {watch_for}", flush=True)
    for i in range(n, 0, -1):
        print(f"  {i} ...", flush=True)
        await asyncio.sleep(1)


async def stream_rhythm(client: IDotMatrixClient, seconds: int = STREAM_SECONDS) -> int:
    """Streams animated level frames at STREAM_HZ, fire-and-forget.

    Paced against a monotonic deadline rather than a flat sleep so BLE write
    latency does not let the effective rate drift below 10 Hz. Returns the
    number of frames written.
    """
    period = 1.0 / STREAM_HZ
    start = time.perf_counter()
    tick = 0
    while time.perf_counter() - start < seconds:
        await client.music_sync._send(build_rhythm_frame(mirrored_levels(tick)), verify=False)
        tick += 1
        next_due = start + tick * period
        delay = next_due - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
    elapsed = time.perf_counter() - start
    print(f"  streamed {tick} frames in {elapsed:.1f}s ({tick / elapsed:.1f} Hz effective)", flush=True)
    return tick


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
                print(f"  {label}: no acks captured", flush=True)

        # --- PHASE GROUP A ---------------------------------------------------

        try:
            await countdown(
                f"PHASE A1 (app effect frame, SPEED={SPEED_FAST})",
                "effect starts -- note the animation pace as a baseline",
            )
            frame = build_app_effect_frame(SPEED_FAST)
            print(f"  sending: {frame.hex(' ')}", flush=True)
            await client.effect._send(frame, verify=False)
            report_acks("A1 (expect 05 00 03 02 01)")
            await asyncio.sleep(10)
        except Exception as ex:
            print(f"  A1 FAILED: {ex!r}", flush=True)

        try:
            await countdown(
                f"PHASE A2 (same frame, SPEED={SPEED_SLOW})",
                "did it slow DRAMATICALLY vs A1?",
            )
            frame = build_app_effect_frame(SPEED_SLOW)
            print(f"  sending: {frame.hex(' ')}", flush=True)
            await client.effect._send(frame, verify=False)
            report_acks("A2 (expect 05 00 03 02 01)")
            await asyncio.sleep(10)
        except Exception as ex:
            print(f"  A2 FAILED: {ex!r}", flush=True)

        try:
            await countdown(
                f"PHASE A3 (same frame, SPEED={SPEED_FAST} again)",
                "fast again? (confirms A2's slowdown was the speed byte, not drift)",
            )
            frame = build_app_effect_frame(SPEED_FAST)
            print(f"  sending: {frame.hex(' ')}", flush=True)
            await client.effect._send(frame, verify=False)
            report_acks("A3 (expect 05 00 03 02 01)")
            await asyncio.sleep(8)
        except Exception as ex:
            print(f"  A3 FAILED: {ex!r}", flush=True)

        # --- PHASE GROUP B ---------------------------------------------------

        # B1 must start from the clock, not from a running effect, so "bars
        # appeared" cannot be confused with leftover effect animation.
        print("\nreturning to clock before the rhythm phases ...", flush=True)
        try:
            await client.clock.show()
            await asyncio.sleep(3)
            acks.clear()
        except Exception as ex:
            print(f"  clock restore before B FAILED: {ex!r}", flush=True)

        try:
            await countdown(
                f"PHASE B1 (COLD stream, {STREAM_SECONDS}s @ {STREAM_HZ}Hz, no mode entry)",
                "do bars/columns appear and dance, or does the clock just stay?",
            )
            await stream_rhythm(client)
            report_acks("B1 (expect SILENCE -- stream is unacked)")
            await asyncio.sleep(3)
        except Exception as ex:
            print(f"  B1 FAILED: {ex!r}", flush=True)

        try:
            await countdown(
                f"PHASE B2 (mic-type frame, 2s, then the SAME {STREAM_SECONDS}s stream)",
                "same question -- does the mode-entry frame make the difference?",
            )
            print(f"  sending mic type: {MIC_TYPE_FRAME.hex(' ')}", flush=True)
            await client.music_sync._send(MIC_TYPE_FRAME, verify=False)
            await asyncio.sleep(2)
            report_acks("B2 mic frame (may ack)")
            await stream_rhythm(client)
            report_acks("B2 stream (expect SILENCE)")
            await asyncio.sleep(3)
        except Exception as ex:
            print(f"  B2 FAILED: {ex!r}", flush=True)

        try:
            await countdown(
                "PHASE B3 (ONE static full-blast frame, all 16 levels = 13)",
                "16 full columns? fewer? rows instead? how tall is 'full'?",
            )
            frame = build_rhythm_frame([LEVEL_MAX] * LEVEL_BYTES)
            print(f"  sending: {frame.hex(' ')}", flush=True)
            await client.music_sync._send(frame, verify=False)
            report_acks("B3")
            await asyncio.sleep(5)
        except Exception as ex:
            print(f"  B3 FAILED: {ex!r}", flush=True)

        print("\ncleanup: clock restored.", flush=True)
        await client.clock.show()


asyncio.run(main())
