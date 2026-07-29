"""P14 -- ack timing, duplication and silence characterization.

WHY THIS PROBE EXISTS
---------------------
Every probe we run reads the fa03 notification stream to decide what the device
did. That instrument has never been calibrated, and on 2026-07-26 it produced a
false finding: probes/probe_effect_length_byte2.py reported "all four 0x0d
effect frames drew no ack whatsoever", which was retracted the same night by
probes/probe_effect_speed_sweep.py. Nothing was wrong with the device. The probe
printed its ack report IMMEDIATELY after the write returned, read an empty list
because the reply was still ~4.3 s away, and then CLEARED that list at the phase
boundary before the reply landed. A whole hardware run was spent on an artifact
of the measuring tool.

So this probe measures the measuring tool. It answers, per command family:

  (a) How long after write completion does the FIRST ack arrive?
  (b) How much does that latency vary across repeats of the SAME command?
  (c) Do acks DUPLICATE (the same (type, subtype) twice for one send)?
  (d) Do acks of an UNEXPECTED (type, subtype) arrive?
  (e) Is any family reliably SILENT?

Its output is the evidence from which future timeout defaults should be derived:
transport.await_device_ack currently defaults to 2.0 s and _CHUNK_ACK_TIMEOUT_
SECONDS to 5.0 s, both chosen without a latency distribution to justify them. A
family whose acks land at 4.3 s is being timed out by a 2.0 s default today.

A family that shows CONSISTENT SILENCE across all 5 repeats is not broken and
must not be written up as broken. It is FIRE-AND-FORGET, and the correct
response is to document it as such and stop waiting on it -- graffiti (type
byte 5) is already known to behave this way and the transport refuses to await
it at all. "Silent" and "ignored" are different claims; only a rendered-result
probe can make the second one.

THE BUG THIS PROBE MUST NOT REPRODUCE
-------------------------------------
Acks are read only after a QUIET_SECONDS window that is deliberately longer than
the longest latency ever observed on this panel (~4.3 s for an effect frame), and
the ack list is NEVER cleared -- not at a phase boundary, not anywhere. Each send
records its start index into the list and reports the slice from that index, so
the whole run's evidence survives to the end and a late ack lands in the next
window rather than vanishing. The final summary re-walks the complete list so
nothing can be silently lost.

DESIGN
------
Command verification is turned OFF for the whole run (set_command_verification
(False), the public fire-and-forget escape hatch). This is essential to the
measurement: with verification ON, _Feature._send AWAITS the ack internally, so
the moment the call returns is the ack's arrival, not the write's completion,
and every latency would read as ~0. With it off, each feature call bottoms out
in transport.write(..., response=True) and returns at GATT write completion --
the t=0 this probe measures from. It also stops a nack from raising
CommandRejectedError mid-run, which matters for the out-of-range brightness
family whose whole point is to draw a rejection.

Seven families, 5 repeats each, so per-command latency gets a mean and a spread
rather than a single sample:

    label  family                          expected ack key
    10     brightness 50 (valid)           (4, 128)  DeviceAck accepted
    20     brightness 200 (out of range)   (4, 128)  DeviceAck rejected?
    30     scoreboard.show                 (10, 128) DeviceAck
    40     effect, app-exact frame         (3, 2)    DeviceAck
    50     clock.show                      (6, 1)    DeviceAck
    60     full DIY frame (display)        (0, 0)    DeviceAck
    70     GIF upload (chunked)            (1, 0)    StatusAck x N

Brightness 200 cannot be sent through client.device.set_brightness: the SDK's
validate_brightness raises ValueError at 5..100 before any bytes are built. The
frame is therefore hand-built -- bytearray([5, 0, 4, 128, 200]) -- and pushed
through client.device._send(verify=False), the same technique the effect sweep
used to put a malformed frame back on the wire. The firmware's own range
enforcement is the thing under test, and the SDK guard would hide it.

Family 60 is preceded by ONE display.invalidate_diy_mode() call, so repeat 1
carries the DIY-entry command (4, 1) ahead of the frame and repeats 2-5 are pure
frames. That is deliberate: repeat 1's extra (4, 1) ack is expected, reported as
an unexpected-key ack, and separates entry cost from frame cost. Without the
invalidate, the driver would still believe it was in DIY mode after the
scoreboard label took the panel out of it, and the frames would be silently
swallowed (hardware evidence 2026-07-20, BleDisplay.invalidate_diy_mode).

Family 70 uploads a freshly generated noise GIF with a UNIQUE seed per repeat.
This is required, not cosmetic: the device keeps a single-slot CRC of the stored
GIF, and re-uploading identical bytes short-circuits to SAVED on chunk 1, which
would measure the dedup fast path instead of the three-way handshake. Each
upload is one of the few places the SDK itself waits on acks, so its t=0 is the
start of the upload and the whole chunk sequence is reported.

THE OPERATOR NEED NOT WATCH THE PANEL FOR THIS PROBE. It is purely a timing
measurement; the visuals are incidental and no visual judgement is asked for.
The scoreboard label is shown once per family only so the operator can tell how
far along the run is, and the two number sets are disjoint (families are
10/20/.../70, repeats are 1..5) so a label can never be misread.

METHOD
------
Device reset (common.reset, 04 00 03 80 -- VERIFIED non-destructive, used live
2026-07-18 to clear a stuck state) to start from a known state, settle, clock
baseline. Nothing in the `experimental` namespace is touched; set_password /
verify_password are never called; nothing is written to ae00/ae01;
delete_device_data is never called. Each family and each repeat is wrapped so
one failure cannot end the run. Cleanup: clock.

READOUT
-------
  * A family whose 5 first-ack latencies cluster tightly => a defensible timeout
    default is mean + generous margin, and await_device_ack's 2.0 s can be
    justified or corrected per family with numbers.
  * A family with a WIDE spread (e.g. 0.3 s to 4.5 s) => no single timeout is
    safe; that family needs the slowest observed latency as its floor, and any
    past probe that waited less than the max has been reading noise.
  * Any family where max latency > 2.0 s => transport.await_device_ack's current
    default TIMES OUT on a healthy device today. That is a live SDK bug, not a
    measurement curiosity, and the number here is the fix.
  * DUPLICATES on a DeviceAck family => ack counting cannot be used to count
    commands; every consumer must be idempotent. (StatusAck duplicates are
    already known and _run_upload_pass already drains them.)
  * UNEXPECTED-KEY acks outside family 60 repeat 1 => something in the SDK is
    emitting commands we did not ask for; identify it before trusting any probe
    that keys on (type, subtype).
  * CONSISTENT SILENCE across all 5 repeats => document that family as
    FIRE-AND-FORGET. Do NOT record it as broken. Re-check with a rendered-result
    probe before making any claim about whether the device acted.
  * INTERMITTENT silence (some repeats ack, some do not) => load-shedding, which
    the 2026-07-25 HCI capture already saw on the brightness dial (~17% nacks
    under rapid repeats). Retry policy, not timeout policy, is the answer.
  * Brightness 200's ack is not an open hypothesis here: P13
    (probes/probe_boundary_sweep.py, 2026-07-25) already hand-built the same
    out-of-range RAW frames (0, 1, 4, 101, 255) and got a hard DeviceAck NACK
    ([05 00 04 80 00]) on every one, no clamping, firmware range exactly
    5..100. Family 20 is expected to reproduce that NACK; this probe's
    contribution is WHERE that ack lands in the latency distribution, not
    whether it exists. A silent or ACCEPTED result here would contradict P13
    and should be treated as a reproduction failure to chase down, not a new
    finding to write up on its own.

USAGE
-----
    python probes/probe_p14_ack_timing.py

Runtime is roughly 8 minutes: 6 flat families x 5 repeats x ~8.5 s, plus 5 GIF
uploads at ~9 s each with their own quiet windows, plus labels and the reset.

RESULT (2026-07-27): CLOSED. No command family tested was silent -- all
seven families (brightness valid, brightness out-of-range, scoreboard,
effect, clock, full DIY frame, chunked GIF upload) acked on every one of
their 5 repeats. First-ack latency clustered by family shape: FLAT
config/native-mode commands (brightness, scoreboard, clock) replied in
roughly 0.13-0.30 s; FULL-FRAME-sized commands (the DIY frame and the effect
command) replied in roughly 0.6-0.9 s. transport.await_device_ack's 2.0 s
default has margin over every family measured here. Brightness 200
(out-of-range, hand-built past the SDK's validation) reproduced P13's hard
NACK, as expected -- see this probe's corrected docstring note citing P13
rather than treating firmware enforcement as an open hypothesis. This run is
also the evidentiary basis for retracting the "0x0d effect frames never ack"
finding elsewhere tonight (probes/probe_effect_length_byte2.py): no family
here, effect included, was ever silent, and capabilities.py's new
common.ack_timing entry records the full picture.
"""

import asyncio
import io
import random
import time

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol.response import (
    STATUS_FAILED,
    STATUS_NEXT_CHUNK,
    STATUS_SAVED,
    DeviceAck,
    StatusAck,
)

ADDRESS = "6D:FD:F8:A0:3E:AF"

REPEATS = 5

# Longer than the brief's 3 s floor ON PURPOSE. The longest latency ever seen on
# this panel is ~4.3 s (effect frame, probes/probe_effect_speed_sweep.py), so a
# 3 s window would clip exactly the family that produced our worst measurement
# bug. 8 s leaves headroom for a duplicate arriving well after the first ack.
QUIET_SECONDS = 8.0

# Scoreboard hold for the once-per-family panel label. Long enough that the
# label's own ack (10, 128) has certainly landed before the first repeat's
# window opens, so it cannot be misattributed to the command under test.
LABEL_SECONDS = 4.0

# The app's 7-color effect palette from the 2026-07-25 HCI capture, in wire
# order -- byte-identical to probes/probe_effect_speed_sweep.py so the two runs
# stay comparable.
APP_EFFECT_COLORS = bytes.fromhex(
    "7f0000"  # dark red
    "7f5100"  # amber
    "7f7f00"  # olive
    "007f00"  # green
    "00007f"  # blue
    "7f007f"  # purple
    "7f7f7f"  # grey
)

# [declared_length, 0, type=3, subtype=2, style, speed, color_count] + colors.
# 0x1c = 28 is the vendor app's correct declared length for a 7-color frame.
APP_EFFECT_FRAME = bytearray([0x1C, 0x00, 0x03, 0x02, 0x00, 100, 0x07]) + APP_EFFECT_COLORS

# Hand-built because validate_brightness raises at 5..100 before any bytes
# exist. Firmware range enforcement is the thing under test.
OUT_OF_RANGE_BRIGHTNESS_FRAME = bytearray([5, 0, 4, 128, 200])

STATUS_NAMES = {
    STATUS_FAILED: "FAILED/doomed",
    STATUS_NEXT_CHUNK: "NEXT_CHUNK",
    STATUS_SAVED: "SAVED",
}


def ack_key(ack: DeviceAck | StatusAck) -> tuple[int, int]:
    return (ack.command_type, ack.command_subtype)


def describe(ack: DeviceAck | StatusAck) -> str:
    """One-line rendering that names the status vocabulary rather than the raw int.

    A StatusAck is never a rejection -- reading status=3 SAVED as a nack is the
    misparse that shipped three broken features (protocol/response.py) -- so the
    two families are spelled differently here on purpose.
    """
    key = f"type={ack.command_type} subtype={ack.command_subtype}"
    if isinstance(ack, StatusAck):
        name = STATUS_NAMES.get(ack.status, f"UNRECOGNIZED({ack.status})")
        return f"StatusAck {key} status={ack.status} {name}  raw={ack.raw.hex(' ')}"
    verdict = "ACCEPTED" if ack.accepted else "*** REJECTED ***"
    return f"DeviceAck {key} {verdict}  raw={ack.raw.hex(' ')}"


def make_noise_gif(seed: int, frames: int = 8) -> bytes:
    """A 32x32 noise GIF, deterministic in `seed`. ~11 KB -> 3 outer chunks.

    Noise, not a pattern: it compresses badly, so even 8 frames comfortably
    cross the 4096-byte chunk boundary and exercise the multi-chunk NEXT_CHUNK
    handshake rather than the single-chunk straight-to-SAVED path. Sized for
    THREE outer chunks on purpose -- enough to show at least two intermediate
    NEXT_CHUNKs before the terminal SAVED, without spending a minute per repeat.
    Callers must vary the seed per upload -- identical bytes hit the device's
    single-slot CRC and short-circuit to SAVED on chunk 1.
    """
    rng = random.Random(seed)
    images = []
    for _ in range(frames):
        im = Image.new("RGB", (32, 32), (0, 0, 0))
        px = im.load()
        for _ in range(300):
            px[rng.randrange(32), rng.randrange(32)] = (
                rng.randrange(256),
                rng.randrange(256),
                rng.randrange(256),
            )
        images.append(im)
    buf = io.BytesIO()
    images[0].save(buf, format="GIF", save_all=True, append_images=images[1:], duration=150, loop=0)
    return buf.getvalue()


def make_marked_frame(base: tuple[int, int, int]) -> bytes:
    """A solid frame with an asymmetric white corner marker, 32x32 RGB.

    Only used so family 60 sends a frame the operator could sanity-check if they
    happen to look; the marker makes a stale or rotated panel obvious. The frame
    content is irrelevant to the timing measurement.
    """
    pixels = bytearray()
    for y in range(32):
        for x in range(32):
            marker = (x < 8 and y < 3) or (x < 3 and y < 8)
            pixels += bytes((255, 255, 255)) if marker else bytes(base)
    return bytes(pixels)


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        # NEVER cleared. Every send records its start index and reports a slice,
        # so a late ack lands in a later window instead of being destroyed --
        # the exact failure that voided probe_effect_length_byte2.py.
        acks: list[tuple[float, DeviceAck | StatusAck]] = []
        unsubscribe = client.add_response_listener(lambda a: acks.append((time.perf_counter(), a)))

        # See DESIGN: with verification on, _send awaits the ack itself and every
        # latency measured here would be ~0.
        client.set_command_verification(False)

        # family -> list of per-repeat records
        results: dict[str, list[dict]] = {}

        async def measure(family: str, expected: tuple[int, int], repeat: int, send) -> None:
            """Send once, let the acks settle, then report and record.

            The ONLY reporting discipline this probe allows: mark, send,
            wait QUIET_SECONDS, read. Never read before the wait; never clear.
            """
            mark = len(acks)
            t_start = time.perf_counter()
            await send()
            t_written = time.perf_counter()

            await asyncio.sleep(QUIET_SECONDS)
            window = acks[mark:]

            print(
                f"  [{family}] repeat {repeat}/{REPEATS}: write completed in "
                f"{t_written - t_start:.3f}s, expected ack key {expected}",
                flush=True,
            )

            seen: set[tuple[int, int, int]] = set()
            duplicates = 0
            unexpected = 0
            first_latency: float | None = None
            for t, ack in window:
                latency = t - t_written
                if first_latency is None:
                    first_latency = latency
                status = ack.status if isinstance(ack, StatusAck) else int(ack.accepted)
                fingerprint = (*ack_key(ack), status)
                tag = ""
                if fingerprint in seen:
                    duplicates += 1
                    tag += "  <DUPLICATE>"
                seen.add(fingerprint)
                if ack_key(ack) != expected:
                    unexpected += 1
                    tag += "  <UNEXPECTED KEY>"
                print(
                    f"      +{latency:6.3f}s after write (+{t - t_start:6.3f}s after send start)  {describe(ack)}{tag}",
                    flush=True,
                )

            if not window:
                # Silence is a result, not an absence of one -- but only across
                # all 5 repeats does it mean fire-and-forget. Say so loudly here
                # and let the summary decide.
                print(f"      *** NO ACKS in {QUIET_SECONDS:.0f}s *** -- record this, it is a result", flush=True)

            results.setdefault(family, []).append(
                {
                    "first_latency": first_latency,
                    "acks": len(window),
                    "duplicates": duplicates,
                    "unexpected": unexpected,
                }
            )

        async def run_family(label_value: int, family: str, expected: tuple[int, int], make_send) -> None:
            """Label the panel once, then run REPEATS measured sends."""
            print(f"\n=== FAMILY {family} -- scoreboard label {label_value} | repeat", flush=True)
            try:
                await client.scoreboard.show(label_value, 0)
                await asyncio.sleep(LABEL_SECONDS)
            except Exception as ex:
                print(f"  label for {family} FAILED (continuing): {ex!r}", flush=True)
            for repeat in range(1, REPEATS + 1):
                try:
                    await measure(family, expected, repeat, make_send(repeat))
                except Exception as ex:
                    print(f"  [{family}] repeat {repeat} FAILED: {ex!r}", flush=True)

        # Known-state entry: reset (04 00 03 80, non-destructive), settle, clock.
        try:
            print("resetting device to a known state ...", flush=True)
            await client.device.reset()
            await asyncio.sleep(4)
            await client.clock.show()
            await asyncio.sleep(3)
            print(f"baseline: clock. {len(acks)} ack(s) logged so far (kept, never cleared).", flush=True)
        except Exception as ex:
            print(f"  reset/clock baseline FAILED: {ex!r}", flush=True)

        # --- family 10: a config command known to ack, valid value -------------
        await run_family(
            10,
            "brightness 50 (valid)",
            (4, 128),
            lambda repeat: lambda: client.device.set_brightness(50),
        )

        # --- family 20: same command, out of the firmware's 5..100 range -------
        await run_family(
            20,
            "brightness 200 (out of range)",
            (4, 128),
            lambda repeat: lambda: client.device._send(OUT_OF_RANGE_BRIGHTNESS_FRAME, verify=False),
        )

        # --- family 30: native mode entry (type 10, subtype 128) ---------------
        await run_family(
            30,
            "scoreboard.show",
            (10, 128),
            lambda repeat: lambda: client.scoreboard.show(repeat, 30),
        )

        # --- family 40: effect command, the app-exact captured frame -----------
        await run_family(
            40,
            "effect (app-exact frame)",
            (3, 2),
            lambda repeat: lambda: client.effect._send(APP_EFFECT_FRAME, verify=False),
        )

        # --- family 50: clock ---------------------------------------------------
        await run_family(
            50,
            "clock.show",
            (6, 1),
            lambda repeat: lambda: client.clock.show(),
        )

        # --- family 60: full DIY frame, the largest single payload --------------
        # The scoreboard label just took the panel out of DIY mode, but the
        # driver's flag does not know that (it cannot see feature-namespace
        # commands). Without this, repeat 1's frame is silently swallowed --
        # hardware evidence 2026-07-20, BleDisplay.invalidate_diy_mode.
        client.display.invalidate_diy_mode()
        frame_colors = [(200, 0, 0), (0, 200, 0), (0, 0, 200), (200, 200, 0), (0, 200, 200)]
        await run_family(
            60,
            "full DIY frame",
            (0, 0),
            lambda repeat: lambda: client.display.show_frame(make_marked_frame(frame_colors[repeat - 1])),
        )

        # --- family 70: chunked upload, the 3-way StatusAck vocabulary ----------
        # Unique seed per repeat: identical bytes would hit the single-slot CRC
        # and short-circuit to SAVED on chunk 1, measuring dedup rather than the
        # handshake. time.time() makes the seeds novel across runs too.
        seed_base = int(time.time())
        await run_family(
            70,
            "gif upload (chunked)",
            (1, 0),
            lambda repeat: lambda: client.gif.upload_bytes(make_noise_gif(seed_base + repeat)),
        )

        # ------------------------------------------------------------------ summary
        print("\n" + "=" * 78, flush=True)
        print("SUMMARY -- first-ack latency is measured from GATT write completion", flush=True)
        print("=" * 78, flush=True)
        header = f"{'family':32} {'n':>2} {'min':>7} {'mean':>7} {'max':>7} {'acks':>5} {'dup':>4} {'silent':>7}"
        print(header, flush=True)
        print("-" * len(header), flush=True)
        for family, records in results.items():
            latencies = [r["first_latency"] for r in records if r["first_latency"] is not None]
            silences = sum(1 for r in records if r["first_latency"] is None)
            total_acks = sum(r["acks"] for r in records)
            duplicates = sum(r["duplicates"] for r in records)
            unexpected = sum(r["unexpected"] for r in records)
            if latencies:
                lo = f"{min(latencies):7.3f}"
                mean = f"{sum(latencies) / len(latencies):7.3f}"
                hi = f"{max(latencies):7.3f}"
            else:
                lo = mean = hi = "      -"
            print(
                f"{family:32} {len(records):>2} {lo} {mean} {hi} {total_acks:>5} {duplicates:>4} {silences:>7}",
                flush=True,
            )
            if unexpected:
                print(f"{'':32} ^ {unexpected} unexpected-key ack(s) -- see the per-repeat log above", flush=True)

        print(f"\nfull ack log: {len(acks)} notification(s) captured across the whole run (never cleared).", flush=True)
        print("\nverdict to record:", flush=True)
        print("  any family with max > 2.0s  => await_device_ack's 2.0s default times out on a", flush=True)
        print("                                 HEALTHY device. Live SDK bug; this number is the fix.", flush=True)
        print("  tight cluster               => that family's timeout default is mean + margin.", flush=True)
        print("  wide spread                 => no single timeout is safe; use the observed max as", flush=True)
        print("                                 the floor and re-read any probe that waited less.", flush=True)
        print("  silent in ALL 5 repeats     => FIRE-AND-FORGET. Document it as such; do NOT record", flush=True)
        print("                                 it as broken. Silence != the device ignored it.", flush=True)
        print("  silent in SOME repeats      => load-shedding (cf. the 2026-07-25 capture's ~17%", flush=True)
        print("                                 brightness-dial nacks). Retry policy, not timeouts.", flush=True)
        print("  duplicates on a DeviceAck   => ack counts cannot count commands; consumers must be", flush=True)
        print("                                 idempotent.", flush=True)

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main())
