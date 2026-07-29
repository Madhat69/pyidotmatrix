"""P10 -- interrupted-upload recovery and saved-data integrity (docs/PROBE_PLAN.md, P10).

WHY THIS PROBE EXISTS
---------------------
`UploadError` is currently a name without a meaning. client.py raises it when a
chunked transfer never reaches a terminal SAVED, and `_send_gif_upload` already
RETRIES the whole upload once, automatically, on the caller's behalf -- but
nobody has ever established what state the device is left in when a transfer
dies partway through. Two questions follow, and both are publication-critical
for native uploads:

  1. Does an interrupted upload DESTROY the gif the device already had? If the
     answer is yes, then every UploadError carries a hidden second failure --
     the previous content is gone too -- and the automatic retry is running
     against a device we have already damaged.
  2. Is that automatic retry SAFE? It restarts from chunk 1 with a fresh
     is_first header on the assumption that a fresh header resets the device's
     receive state. That assumption is inferred from clean uploads that
     happened to follow abandoned ones. It has never been tested against a
     deliberate mid-chunk abort.

WHAT IS ALREADY KNOWN AND IS NOT RE-DERIVED HERE
------------------------------------------------
  * GIF upload speaks the three-way StatusAck vocabulary shared with Timer and
    Schedule: 1 = NEXT_CHUNK, 3 = SAVED (terminal success), 0 = FAILED. A
    mid-stream 0 rejects that chunk and SILENTLY DOOMS the whole transfer --
    later chunks keep acking 1, no terminal 3 ever arrives, and nothing is
    saved (P2e, 2026-07-25, visually proven with tinted fixtures).
  * The device recognizes only the CURRENTLY STORED gif, by a single-slot CRC.
    Not a library: a gif stored earlier but since displaced answers NEXT_CHUNK,
    not SAVED (P2c/P2d, 2026-07-25).
  * Chunk 1 of an ALREADY-STORED gif returns SAVED and switches playback in
    about a second. That is the `gif.activate_stored()` primitive, and this
    probe leans on it as its measuring instrument -- see below.
  * Case (b), the first-OUTER-CHUNK abandon, is already covered at the protocol
    level by probes/probe_gif_crc_cache3.py phase 2: chunk 1 of a never-uploaded
    gif returns status 1 (the device waits for chunk 2) and a later full upload
    was unaffected. It is re-run here only as the control that anchors the
    other two, at minimal cost. Cases (a) and (c) are the genuinely open ones.

THE MEASURING INSTRUMENT
------------------------
"Does the previously saved content still work?" has an exact, one-second,
zero-ambiguity test thanks to single-slot recognition: send chunk 1 of the OLD
gif and read its one StatusAck.

    SAVED (3)      -> the device still holds the old bytes. Storage INTACT.
                      Playback switches to it, so the panel confirms it too.
    NEXT_CHUNK (1) -> those are NOT the stored bytes any more. The interrupted
                      upload DISPLACED OR CORRUPTED the saved gif -- which is
                      the headline failure this probe exists to detect.

That is exactly what `client.gif.activate_stored(old_bytes)` does, and its
boolean return is the reading. A False return leaves a dangling one-chunk
transfer, which is hardware-verified inert and safely abandoned.

FIXTURES
--------
  BASE ("the known-good saved GIF"): four frames, a 6x6 WHITE block hopping
       clockwise TL -> TR -> BR -> BL over a dim GREEN field, ~4 fps. Small
       enough to be ONE outer chunk. Correct playback is unmistakable and
       cannot be confused with the replacement.
  BIG  ("the larger replacement"): 16 frames of dense random-noise confetti,
       tens of kilobytes, SIX-ish outer chunks -- enough that "a middle chunk"
       is a real place. Noise versus a hopping block is not a subtle
       distinction; the operator can call it at a glance. NOTE: this is not the
       byte-identical fixture from the earlier gif probes (those used 32 frames),
       so every BIG upload here is a genuine cold transfer with no chance of
       accidental CRC recognition.

SAFE SENDER vs RAW SENDER -- WHICH PHASE USES WHICH, AND WHY IT MATTERS
------------------------------------------------------------------------
There is a known CHUNK-2 RACE: a blind back-to-back sender fires chunk 2 while
the device is still digesting chunk 1's header, and that chunk is silently
rejected -- roughly half the time on the reference panel. The client's sender is
now status-aware and paced, which removes it. The distinction is load-bearing
here, because a phase that failed to the race would masquerade as a finding
about interruption. So, explicitly:

  SAFE (paced, status-aware -- `_run_upload_pass` / `gif.upload_bytes`):
    - the initial BASE upload,
    - getting the transfer to the middle in case (c),
    - every recovery re-upload,
    - every activate_stored check.
  DELIBERATELY RAW (one bare `transport.write`, unpaced, no ack awaited):
    - the interruption itself in cases (a) and (c), and ONLY that.
  The raw write is the interruption. Nothing else in this probe is unpaced,
  so any failure that is not at an interruption point is not a race artifact.

THE THREE INTERRUPTION POINTS
------------------------------
Driven below the high-level upload, because `gif.upload_bytes` has no way to
stop partway. `gif.build_packets` returns a list of OUTER CHUNKS, each a list of
protocol packets (split at 509 bytes); `transport.write_packets` then re-splits
those to the link's negotiated GATT write size. Both granularities are printed
at the start of the run, since "one BLE packet" means different things at each.

  (a) AFTER ITS FIRST BLE PACKET. One bare `transport.write` of exactly
      write_size bytes taken from the head of chunk 1's first protocol packet,
      then stop. The device has seen a valid 16-byte gif header declaring a
      4112-byte chunk and then nothing. PREDICTION: no ack at all, because no
      complete chunk was ever delivered. An ack here would itself be a finding.
  (b) AFTER ITS FIRST OUTER CHUNK. `_run_upload_pass(..., max_chunks=1)` --
      chunk 1 complete, its one ack read, then stop. PREDICTION: NEXT_CHUNK (1);
      the control case, matching probe_gif_crc_cache3.py phase 2.
  (c) DURING A MIDDLE OUTER CHUNK. Paced through the first half of the chunks
      normally, then a bare `transport.write` of one write_size-sized piece of
      the NEXT chunk, then stop. The device is left holding a partial
      continuation chunk in the middle of an accepted transfer -- the worst
      case, and the one most like a real-world BLE drop.

PER-CASE PROCEDURE (identical for all three, so the cases are comparable)
--------------------------------------------------------------------------
  1. Scoreboard phase label (100/200/300), which also clears BASE off the panel
     -- so "BASE comes back" in step 4 is unambiguous rather than a screen that
     never changed. Flat commands are unaffected by anything else here.
  2. Interrupt.
  3. Observe: does partial data become VISIBLE? does the panel glitch, freeze,
     or go black? Acks are reported only after the settle window.
  4. RECONNECT (disconnect, pause, connect), then activate_stored(BASE): is the
     previously saved content still there and still playable?
  5. Re-upload BIG with the safe sender: does the same content now succeed?
     Record the handshake and the wall time. If it raises UploadError, retry
     ONCE after common.reset() -- and if THAT is what rescues it, then
     "recovery requires a reset" is the finding, which is precisely one of the
     things P10 is chartered to record.
  6. Restore BASE, so the next case starts from the identical known-good state.

Finally, one DIY frame after all three cases: if native uploads can leave the
panel unable to accept frames, the driver would need a DIY re-entry rule, and
this is where that would show.

ACK INSTRUMENTATION -- THE BUG THIS PROBE REFUSES TO REPEAT
------------------------------------------------------------
On 2026-07-26 a probe printed its ack report IMMEDIATELY after sending and
cleared the list at the phase boundary, before the device's reply (~0.3s, up to
~4.3s) had arrived. It read empty every time and published "no ack whatsoever"
as a device behaviour. It was an instrumentation bug and it cost a hardware
run. Here, report_acks is ASYNC, sleeps ACK_SETTLE_SECONDS BEFORE reading,
prints the send->ack delta for every entry, and clears only AFTER printing.
That matters more in this probe than in most, because SILENCE IS A PREDICTED
RESULT in case (a) -- and a false silence would be indistinguishable from a
real one.

READOUT
-------
  * activate_stored(BASE) returns SAVED after all three interruptions => an
    interrupted upload does NOT touch stored content. `UploadError` then means
    exactly "the new content did not arrive", the old content is still live and
    still playable, and the automatic whole-upload retry is SAFE. This is the
    result that lets native uploads be documented as non-destructive.
  * activate_stored(BASE) returns NEXT_CHUNK after any case => that
    interruption DESTROYED or DISPLACED the saved gif. `UploadError` then means
    "the new content did not arrive AND the old content is gone", automatic
    retry runs against an already-damaged device, and the driver must say so.
    Record WHICH case did it: (a) means merely opening a transfer is
    destructive; (c) means the damage happens once chunks are being accepted.
  * The panel shows PARTIAL or CORRUPTED content at step 3 => the device
    renders from a buffer it is still filling. That is a visible-artifact bug
    class we have not seen before; record it prominently with the case.
  * The re-upload succeeds without a reset in every case => a fresh is_first
    header does reset the device's receive state, confirming the assumption
    `_send_gif_upload`'s retry is built on.
  * The re-upload needs common.reset() => the retry as written CANNOT recover
    on its own, and `_send_gif_upload` is claiming a resilience it does not
    have. Highest-priority driver bug this probe could surface.
  * A re-upload that reports SAVED but plays the WRONG animation => storage and
    the CRC slot have diverged; treat every dedup fast path as suspect.
  * The closing DIY frame renders => native upload failures do not poison the
    frame pipeline. It does not => the driver needs a DIY re-entry (or reset)
    rule after any UploadError.

USAGE
-----
    python probes/probe_p10_interrupted_upload.py          # all three cases
    python probes/probe_p10_interrupted_upload.py a c      # selected cases

Case letters are a, b, c. Selecting a subset re-runs those cases in isolation;
nothing else about a case changes, and the BASE fixture is always established
first.

Estimated runtime: ~5 minutes for all three cases (~60 s each, including one
reconnect per case, plus ~45 s of setup and the closing health check). Well
under the ~15 minute budget; the reconnects are the only unpredictable cost.

SAFETY
------
No graffiti commands at all, so the 255-pixel-per-command guardrail (a
256-pixel command crashed the panel's BLE stack on 2026-07-25) is never
approached. No set_password/verify_password, no ae00/ae01 writes, no
experimental namespace, no delete_device_data. common.reset() (04 00 03 80) is
verified-safe and is used for the baseline and, if needed, as the recorded
recovery step. Every raw write is a single write of at most one negotiated
write-size worth of bytes.

RESULT (2026-07-27): CLOSED. activate_stored(BASE) returned SAVED after all
three interruption cases -- (a) one raw BLE packet then stop, (b) one
complete outer chunk then stop, (c) paced through the first half of the
chunks then one raw partial-chunk write mid-transfer. An interrupted upload
DOES NOT touch previously stored content: `UploadError` means only "the new
content did not arrive", never "and the old content is gone too", which is
exactly what makes `_send_gif_upload`'s automatic whole-upload retry SAFE to
run unattended. Two further observations from this run: a GIF that is
ALREADY PLAYING FREEZES the instant a new upload starts arriving, rather
than continuing to animate through the transfer; and
`gif.activate_stored()` RESTARTS PLAYBACK AT FRAME 0 rather than resuming
wherever the previous playback of that content had reached -- it is an
instant-switch primitive (P2d), not a pause/resume one. The closing DIY
health-check frame rendered after all three cases, so interrupted native
uploads do not poison the frame pipeline. capabilities.py's gif.upload_file
entry is updated with all of the above.
"""

import asyncio
import io
import random
import sys
import time

from PIL import Image, ImageDraw

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.client import (
    _GIF_ACK_SUBTYPE,
    _GIF_ACK_TYPE,
    _run_upload_pass,
)
from pyidotmatrix.exceptions import UploadError
from pyidotmatrix.protocol import gif

ADDRESS = "6D:FD:F8:A0:3E:AF"

# How long to wait after a send before READING the ack list. Non-negotiable --
# see the ack-instrumentation section of the module docstring. Case (a) PREDICTS
# silence, so a premature read would manufacture exactly the result we are
# trying to test for.
ACK_SETTLE_SECONDS = 2.0

LABEL_SECONDS = 4
OBSERVE_SECONDS = 8
RECONNECT_PAUSE_SECONDS = 3

CANVAS = 32
BASE_TINT = (0, 255, 0)  # BASE plays over a dim GREEN field
NOISE_FRAMES = 16  # ~6 outer chunks: enough for a real "middle"
NOISE_PIXELS_PER_FRAME = 300
NOISE_SEED = 210  # not any seed used by the earlier gif probes

CASES = ("a", "b", "c")


def select_cases(argv: list[str]) -> tuple[str, ...]:
    """Which interruption cases to run, from the command line. Parsed before the
    device is touched, so a typo cannot half-run the matrix."""
    if not argv:
        return CASES
    chosen = tuple(arg.lower() for arg in argv)
    unknown = [arg for arg in chosen if arg not in CASES]
    if unknown:
        print(f"unrecognized case(s) {unknown}; accepted: {', '.join(CASES)} (or no argument for all)", flush=True)
        raise SystemExit(2)
    return tuple(case for case in CASES if case in chosen)  # canonical order, deduped


def build_base_gif() -> bytes:
    """BASE: a 6x6 white block hopping clockwise over a dim green field. One
    outer chunk, so its upload goes straight to SAVED with no NEXT_CHUNK round
    trip and cannot trip the chunk-2 race."""
    background = tuple(channel // 3 for channel in BASE_TINT)
    frames = []
    for x, y in ((2, 2), (24, 2), (24, 24), (2, 24)):  # TL -> TR -> BR -> BL
        image = Image.new("RGB", (CANVAS, CANVAS), background)
        ImageDraw.Draw(image).rectangle([x, y, x + 5, y + 5], fill=(255, 255, 255))
        frames.append(image)
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=250, loop=0)
    return buffer.getvalue()


def build_big_gif() -> bytes:
    """BIG: dense random-noise confetti, deliberately many outer chunks.

    Same shape as the generator the earlier gif probes used, but 16 frames and a
    fresh seed -- so these bytes have never been on this device and every BIG
    upload is a genuine cold transfer, with no chance of single-slot CRC
    recognition short-circuiting the very interruption we are trying to stage.
    """
    rng = random.Random(NOISE_SEED)
    frames = []
    for _ in range(NOISE_FRAMES):
        image = Image.new("RGB", (CANVAS, CANVAS), (0, 0, 0))
        pixels = image.load()
        for _ in range(NOISE_PIXELS_PER_FRAME):
            pixels[rng.randrange(CANVAS), rng.randrange(CANVAS)] = (
                rng.randrange(256),
                rng.randrange(256),
                rng.randrange(256),
            )
        frames.append(image)
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=150, loop=0)
    return buffer.getvalue()


async def main(cases: tuple[str, ...]) -> None:
    print(f"cases selected: {', '.join(cases)}", flush=True)
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        transport = client._transport
        acks: list[tuple[float, object]] = []
        unsubscribe = client.add_response_listener(lambda ack: acks.append((time.perf_counter(), ack)))

        async def report_acks(label: str, sent_at: float) -> None:
            """Waits for the device to actually reply, THEN reports and clears.

            The sleep is the point. Reading the list synchronously after a send
            is the 2026-07-26 instrumentation bug that invented a device
            behaviour out of nothing. Silence is a PREDICTED outcome in case
            (a), so it has to be real silence, measured after a full settle
            window, with every delta printed -- and the list is cleared only
            after it has been reported.
            """
            await asyncio.sleep(ACK_SETTLE_SECONDS)
            if acks:
                print(f"  {label}: {len(acks)} ack(s) after {ACK_SETTLE_SECONDS}s:", flush=True)
                for at, ack in acks:
                    print(f"    send+{at - sent_at:6.2f}s  {ack!r}", flush=True)
            else:
                print(
                    f"  {label}: *** ZERO ACKS within {ACK_SETTLE_SECONDS}s of the send ***",
                    flush=True,
                )
            acks.clear()

        async def reconnect(reason: str) -> None:
            """Explicit disconnect/reconnect between an interruption and its
            inspection, as P10 requires. The response listener lives on the
            transport's own list and survives the cycle; connect() re-subscribes
            to the notify characteristic, so acks keep flowing afterwards."""
            print(f"  reconnecting ({reason}) ...", flush=True)
            started = time.perf_counter()
            try:
                await client.disconnect()
                await asyncio.sleep(RECONNECT_PAUSE_SECONDS)
                await client.connect()
                await asyncio.sleep(1)
                print(f"  reconnected in {time.perf_counter() - started:.2f}s", flush=True)
            except Exception as ex:
                print(f"  RECONNECT FAILED: {ex!r} -- subsequent readings for this case are suspect", flush=True)
            acks.clear()

        async def upload_base(note: str) -> bool:
            """Puts BASE back in the device's single storage slot with the safe
            sender, so every case starts from the identical known-good state."""
            try:
                started = time.perf_counter()
                await client.gif.upload_bytes(base_bytes)
                print(f"  BASE upload ({note}) OK in {time.perf_counter() - started:.2f}s", flush=True)
                await report_acks(f"BASE upload ({note})", started)
                return True
            except Exception as ex:
                print(f"  BASE upload ({note}) FAILED: {ex!r}", flush=True)
                acks.clear()
                return False

        base_bytes = build_base_gif()
        big_bytes = build_big_gif()
        base_chunks = gif.build_packets(base_bytes)
        big_chunks = gif.build_packets(big_bytes)

        # --- baseline ---------------------------------------------------------
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

        write_size = await transport._resolve_write_size(response=False)
        print("\nfixtures and granularity:", flush=True)
        print(f"  BASE: {len(base_bytes)} bytes -> {len(base_chunks)} outer chunk(s)", flush=True)
        print(f"  BIG : {len(big_bytes)} bytes -> {len(big_chunks)} outer chunk(s)", flush=True)
        print(
            f"  BIG chunk 1: {len(big_chunks[0])} protocol packet(s), first is {len(big_chunks[0][0])} bytes",
            flush=True,
        )
        print(f"  negotiated GATT write size: {write_size} bytes -- one raw write sends this many", flush=True)
        if len(big_chunks) < 4:
            print(
                f"  *** WARNING: BIG has only {len(big_chunks)} outer chunks; case (c)'s"
                f" 'middle' is weak. Raise NOISE_FRAMES and re-run. ***",
                flush=True,
            )
        # Zero-based index of the chunk we abort INSIDE; chunks before it are
        # sent normally. Clamped to a real index so a smaller-than-expected BIG
        # degrades into a weaker case rather than an IndexError.
        middle_chunk = min(max(1, len(big_chunks) // 2), len(big_chunks) - 1)
        print(f"  case (c) will pace chunks 1..{middle_chunk} then abort inside chunk {middle_chunk + 1}", flush=True)

        # --- establish the known-good saved GIF -------------------------------
        print("\n=== SETUP: establish BASE as the saved GIF ===", flush=True)
        if not await upload_base("initial"):
            print("  cannot establish the known-good state; aborting the run.", flush=True)
            unsubscribe()
            await client.clock.show()
            return
        print(
            f"  WATCH ({OBSERVE_SECONDS}s): a GREEN field with a WHITE block hopping"
            f" CLOCKWISE TL -> TR -> BR -> BL. This is the content whose survival"
            f" every case below is testing.",
            flush=True,
        )
        await asyncio.sleep(OBSERVE_SECONDS)

        summary: list[tuple[str, str, str, str]] = []  # case, interruption ack, old content, recovery

        for case in cases:
            print(f"\n=================== CASE ({case}) ===================", flush=True)
            interruption_note = "-"
            old_content_note = "-"
            recovery_note = "-"

            # 1. Phase label. Also clears BASE off the panel, so "BASE comes
            #    back" in step 4 is a real observation and not a screen that
            #    simply never changed.
            try:
                await client.scoreboard.show({"a": 100, "b": 200, "c": 300}[case], 0)
                await asyncio.sleep(LABEL_SECONDS)
                acks.clear()
            except Exception as ex:
                print(f"  phase label FAILED: {ex!r}", flush=True)

            # 2. The interruption.
            try:
                if case == "a":
                    # DELIBERATELY RAW: exactly one GATT write, taken from the
                    # head of chunk 1's first protocol packet. The device sees a
                    # valid header declaring a chunk it will never finish
                    # receiving.
                    piece = bytes(big_chunks[0][0][:write_size])
                    print(f"  (a) RAW: one {len(piece)}-byte write of chunk 1, then STOP", flush=True)
                    sent_at = time.perf_counter()
                    await transport.write(piece, response=False)
                    await report_acks("(a) after one BLE packet -- SILENCE IS THE PREDICTION", sent_at)
                    interruption_note = "1 raw write of chunk 1"
                elif case == "b":
                    # SAFE sender, capped at one chunk: the control case.
                    print("  (b) SAFE paced sender, max_chunks=1: chunk 1 complete, then STOP", flush=True)
                    sent_at = time.perf_counter()
                    result = await _run_upload_pass(
                        transport, big_chunks, _GIF_ACK_TYPE, _GIF_ACK_SUBTYPE, max_chunks=1
                    )
                    print(f"  (b) pass ended {result.outcome.name} at chunk {result.chunk_index + 1}", flush=True)
                    await report_acks("(b) after one outer chunk -- expect NEXT_CHUNK (1)", sent_at)
                    interruption_note = f"chunk 1 complete, {result.outcome.name}"
                else:
                    # SAFE sender to reach the middle, then DELIBERATELY RAW for
                    # the abort itself -- the only unpaced write in this case.
                    print(f"  (c) SAFE paced sender through chunks 1..{middle_chunk} ...", flush=True)
                    sent_at = time.perf_counter()
                    result = await _run_upload_pass(
                        transport, big_chunks, _GIF_ACK_TYPE, _GIF_ACK_SUBTYPE, max_chunks=middle_chunk
                    )
                    print(f"  (c) paced pass ended {result.outcome.name} at chunk {result.chunk_index + 1}", flush=True)
                    await report_acks(f"(c) chunks 1..{middle_chunk} -- expect NEXT_CHUNK (1) each", sent_at)
                    piece = bytes(big_chunks[middle_chunk][0][:write_size])
                    print(
                        f"  (c) RAW: one {len(piece)}-byte write INSIDE chunk {middle_chunk + 1}, then STOP",
                        flush=True,
                    )
                    sent_at = time.perf_counter()
                    await transport.write(piece, response=False)
                    await report_acks(f"(c) partial chunk {middle_chunk + 1} -- SILENCE IS THE PREDICTION", sent_at)
                    interruption_note = f"chunks 1..{middle_chunk} paced, partial chunk {middle_chunk + 1}"
            except Exception as ex:
                print(f"  interruption FAILED: {ex!r}", flush=True)
                interruption_note = f"FAILED {ex!r}"

            # 3. Observe the panel while the transfer is abandoned.
            print(
                f"  WATCH ({OBSERVE_SECONDS}s): is ANYTHING visible from the abandoned upload?"
                f" partial noise? corruption? a freeze, a glitch, a black screen?"
                f" (Expected: nothing changes -- the scoreboard or clock stays up.)",
                flush=True,
            )
            await asyncio.sleep(OBSERVE_SECONDS)

            # 4. Reconnect, then ask the device whether it still holds BASE.
            await reconnect(f"case {case} inspection")
            try:
                sent_at = time.perf_counter()
                still_stored = await client.gif.activate_stored(base_bytes)
                verdict = "SAVED -- storage INTACT" if still_stored else "NEXT_CHUNK -- storage LOST/DISPLACED"
                print(f"  old-content check: {verdict}", flush=True)
                await report_acks("activate_stored(BASE)", sent_at)
                print(
                    f"  WATCH ({OBSERVE_SECONDS}s): does the GREEN hopping-block animation come back?"
                    f" (It should if and only if the check above said SAVED.)",
                    flush=True,
                )
                await asyncio.sleep(OBSERVE_SECONDS)
                old_content_note = verdict
            except Exception as ex:
                print(f"  old-content check FAILED: {ex!r}", flush=True)
                old_content_note = f"FAILED {ex!r}"

            # 5. Re-upload the same replacement content, properly this time.
            try:
                started = time.perf_counter()
                try:
                    await client.gif.upload_bytes(big_bytes)
                    recovery_note = f"clean re-upload in {time.perf_counter() - started:.2f}s"
                    print(f"  recovery: {recovery_note}", flush=True)
                except UploadError as ex:
                    # The retry inside _send_gif_upload has already been spent.
                    # If a reset is what rescues this, "recovery requires a
                    # reset" is the finding P10 is chartered to record.
                    print(f"  recovery re-upload raised UploadError: {ex!r}", flush=True)
                    print("  escalating: common.reset() (04 00 03 80, verified-safe) then ONE more attempt", flush=True)
                    await client.device.reset()
                    await asyncio.sleep(4)
                    started = time.perf_counter()
                    await client.gif.upload_bytes(big_bytes)
                    recovery_note = f"needed common.reset() first, then {time.perf_counter() - started:.2f}s"
                    print(f"  recovery: {recovery_note} *** RESET WAS REQUIRED -- record this ***", flush=True)
                await report_acks("recovery upload of BIG", started)
                print(
                    f"  WATCH ({OBSERVE_SECONDS}s): dense multicoloured NOISE confetti, animating."
                    f" Report a frozen frame, a green hopping block, or a blank panel.",
                    flush=True,
                )
                await asyncio.sleep(OBSERVE_SECONDS)
            except Exception as ex:
                print(f"  recovery FAILED even after a reset: {ex!r}", flush=True)
                recovery_note = f"FAILED {ex!r}"

            # 6. Restore the known-good state for the next case.
            await upload_base(f"restore after case {case}")

            summary.append((case, interruption_note, old_content_note, recovery_note))

        # --- closing health check: can the panel still take a DIY frame? ------
        print("\n=== HEALTH CHECK: one DIY frame after all the interrupted uploads ===", flush=True)
        try:
            # invalidate_diy_mode is mandatory: gif/clock/scoreboard all took the
            # panel out of DIY behind the display's back, and a frame sent into a
            # non-DIY panel is SILENTLY SWALLOWED while still acking accepted=True.
            client.display.invalidate_diy_mode()
            frame = bytearray(CANVAS * CANVAS * 3)
            for y in range(CANVAS):  # a chiral corner-keyed frame
                for x in range(CANVAS):
                    if x < 4 and y < 4:
                        colour = (255, 0, 0)  # TL red
                    elif x >= CANVAS - 4 and y < 4:
                        colour = (0, 255, 0)  # TR green
                    elif x < 4 and y >= CANVAS - 4:
                        colour = (0, 0, 255)  # BL blue
                    elif x >= CANVAS - 4 and y >= CANVAS - 4:
                        colour = (255, 255, 255)  # BR white
                    else:
                        colour = (0, 0, 0)
                    offset = (y * CANVAS + x) * 3
                    frame[offset : offset + 3] = bytes(colour)
            sent_at = time.perf_counter()
            await client.display.show_frame(bytes(frame), wait_for_device=True)
            await report_acks("DIY health-check frame (expect 05 00 00 00 01)", sent_at)
            print(
                f"  WATCH ({OBSERVE_SECONDS}s): black panel, four corner blocks --"
                f" TL=RED TR=GREEN BL=BLUE BR=WHITE. If nothing appears, native upload"
                f" failures poison the frame pipeline and the driver needs a re-entry rule.",
                flush=True,
            )
            await asyncio.sleep(OBSERVE_SECONDS)
        except Exception as ex:
            print(f"  DIY health check FAILED: {ex!r}", flush=True)

        # --- summary ----------------------------------------------------------
        print("\n---- case summary ----", flush=True)
        print(f"{'case':<6} {'interruption':<44} {'old content':<38} recovery", flush=True)
        for case, interruption_note, old_content_note, recovery_note in summary:
            print(f"{case:<6} {interruption_note:<44} {old_content_note:<38} {recovery_note}", flush=True)

        print("\nverdict to record:", flush=True)
        print("  SAVED in every case      => interrupted uploads do NOT touch stored content;", flush=True)
        print("                              UploadError means only 'the new content did not", flush=True)
        print("                              arrive', and the automatic retry is SAFE.", flush=True)
        print("  NEXT_CHUNK in any case   => that interruption DESTROYED the saved gif; the", flush=True)
        print("                              automatic retry runs against a damaged device.", flush=True)
        print("  partial data visible     => the device renders from a buffer it is still", flush=True)
        print("                              filling. New artifact class; record prominently.", flush=True)
        print("  reset needed to recover  => _send_gif_upload's whole-upload retry claims a", flush=True)
        print("                              resilience it does not have. Driver bug.", flush=True)
        print("  DIY frame does not render => native upload failures poison the frame pipeline.", flush=True)

        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


asyncio.run(main(select_cases(sys.argv[1:])))
