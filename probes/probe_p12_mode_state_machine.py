"""P12 -- command-order and display-mode state machine.

WHY THIS PROBE EXISTS
---------------------
Every mode we have tested, we have tested in ISOLATION: enter it from a clock
baseline, look at it, go back to clock. That tells us nothing about the edges
between modes, and the edges are where the SDK actually hurts. The one hard
piece of evidence we have is a failure: on 2026-07-20 a native text takeover
ended, the daemon sent its reclaim frame, and the frame was SILENTLY SWALLOWED
-- BleDisplay._diy_mode_enabled still said "we are in DIY mode", so no DIY-entry
command was sent, and a full frame sent into text mode is dropped. Graffiti
deltas painted through; only a later periodic keyframe healed the panel. That is
the whole reason invalidate_diy_mode() exists, and it is currently the embedder's
job to know when to call it -- undocumented knowledge of device state, exactly
what P12 is meant to remove.

So the question at EVERY transition here is one thing: after mode X, does the
next full frame land on its own, or does it need a forced DIY re-entry first?

HOW THAT QUESTION IS MADE VISIBLE RATHER THAN INFERRED
------------------------------------------------------
Every sequence ends in a RECLAIM PAIR -- two frames, back to back, with a watch
window after each:

    attempt A (NAIVE)  -- show_frame() with NO invalidate_diy_mode(). This is
                          what a caller who does not know about DIY state would
                          write. Base colour RED.
    attempt B (FORCED) -- invalidate_diy_mode(), then show_frame(). This forces
                          the mode-1 entry that is hardware-proven to take from
                          any panel state. Base colour GREEN.

The readout is then direct, not deduced:

    panel turns RED in window A    => NO re-entry needed after that mode. The
                                      SDK can leave the flag alone.
    panel stays on the OLD mode
    through window A, then turns
    GREEN in window B              => RE-ENTRY IS REQUIRED after that mode. The
                                      SDK must invalidate automatically when
                                      that mode's command goes out.
    panel stays on the old mode
    through BOTH windows           => the reclaim path is broken for that mode
                                      entirely -- a much bigger finding, and one
                                      no amount of flag-fiddling fixes.
    panel turns GREEN in window A  => impossible; the probe has a bug, stop and
                                      report it rather than recording a result.

RED and GREEN mean the same thing in every sequence, so the operator learns the
convention once. Staleness is caught by the frame content itself, not by colour
alone: every frame carries N white 3x3 blocks along the TOP edge, where N is the
sequence number 1-5, plus a single white 3x3 anchor block in the BOTTOM-LEFT
corner. A frame left over from an earlier sequence therefore shows the WRONG
BLOCK COUNT, and a half-updated or rotated panel is obvious -- under a 180-degree
rotation the counting blocks move to the bottom and the anchor to the top-right.
A plain solid colour would have taught nothing here, since a stale red and a
fresh red look identical.

THE ACK-REPORTING BUG THIS PROBE MUST NOT REPRODUCE
---------------------------------------------------
On 2026-07-26 two probes printed their ack reports IMMEDIATELY after the write
returned -- before the device's reply, which can take ~4.3 s on this panel -- and
then cleared the ack list at the phase boundary, destroying the evidence. That
produced the false finding "these frames are never acked" and cost a hardware
run (retracted in probes/probe_effect_speed_sweep.py). Here: every step waits
SETTLE_SECONDS (6 s, comfortably past the worst latency ever measured) before
reading acks, the ack list is NEVER cleared -- each step reports a slice from its
own start index -- and every ack is printed with its wall-clock delta from the
send that (probably) caused it.

THE FIVE SEQUENCES (docs/PROBE_PLAN.md P12)
-------------------------------------------
1. DIY frame -> text -> full frame
2. DIY frame -> clock -> graffiti -> full frame
3. GIF -> effect -> DIY frame
4. Clock -> countdown -> chronograph -> clock
5. Power off -> command -> power on -> full frame

Sequence 3's reclaim is the interesting one: O-27 (2026-07-17) found that DIY
entry mode 3 does NOT reliably take over an EFFECT state, which is why the
daemon now always requests clear=True. BleDisplay defaults to clear=True (mode
1), so attempt B here should take -- if it does not, mode 1's "always takes"
claim needs qualifying.

Sequence 4 carries the paused-countdown branch flagged in P7: we have seen a
PAUSED countdown hijack chronograph commands. This probe arms a countdown, lets
it tick, PAUSES it, and only then sends the full chronograph vocabulary
(reset/start/pause/resume), recording the ack and the panel for each. GlanceOS
M7 renders timers itself and must never trip over device state the vendor app
left behind, so "what does a chronograph command do to a paused countdown" is a
shipping question, not a curiosity. The countdown is explicitly stopped
afterwards so the run leaves no armed timer on the device.

Sequence 5 uses the SDK's SOFTWARE power command -- client.common.turn_off() /
turn_on() (protocol.common.build_set_power, [5 0 7 1 on]). Nothing is unplugged;
BLE stays connected throughout, which is the point. While the screen is off the
probe sends a brightness change and a scoreboard (a MODE change), then powers
back on. Three outcomes are distinguishable at power-on: the scoreboard appears
(commands sent while off were executed, just invisible), the pre-off mode
appears (commands while off were dropped and prior mode resumed), or the clock
appears (power-on resets to clock regardless).

OPERATOR NOTES -- READ THE PANEL LABELS
---------------------------------------
Watch the panel throughout; this probe is entirely visual apart from the ack
timings. You never need the console.

    0 | 0   RUN START MARKER. The run has begun. Shown once, then the clock for
            a moment, then the sequence 1 label. 0 is reserved for this marker
            and no sequence ever uses it, so 0 | 0 can only mean "starting".
    1 | 0   sequence 1 begins        4 | 0   sequence 4 begins
    2 | 0   sequence 2 begins        5 | 0   sequence 5 begins
    3 | 0   sequence 3 begins

A label appears ONCE, at the start of its sequence, and is held ~4 s. Everything
you see after a label, until the next label, belongs to that sequence. There are
deliberately NO labels between the steps within a sequence, and none between a
sequence's last mode step and its RED/GREEN reclaim pair. That is not an
oversight: the scoreboard is itself a native-mode command, so a label inserted
between steps would become part of the transition under test. Sequence 1 is
DIY -> text -> frame; labelling every step would silently make it DIY ->
scoreboard -> text -> scoreboard -> frame, and a label placed just before a
reclaim pair would change the question from "does DIY need re-entry after TEXT"
to "after SCOREBOARD" -- invalidating the only result the sequence exists to
produce. (The P7 author flagged the same confound independently.)

The labels do double duty as a render check: each sequence's FIRST step says
what should replace the label, so if the label numbers are STILL on screen when
that step's watch window ends, the step never rendered -- which is itself a
result worth recording.

The two things to actually report per sequence are unchanged: which colour the
reclaim pair landed on (RED = no DIY re-entry needed, GREEN = re-entry
required), and the white-block count on the top edge, which says WHICH sequence
painted the frame you are looking at. What to report per step is printed before
its watch window opens.

METHOD
------
Device reset (common.reset, 04 00 03 80 -- VERIFIED non-destructive, used live
2026-07-18 to clear a stuck state), settle, clock baseline. Command verification
is turned OFF for the whole run so a nack cannot raise CommandRejectedError and
end a sequence early -- acks still arrive through the response listener, which
fires regardless. Every step and every sequence is wrapped so one failure cannot
end the run. Nothing in the `experimental` namespace is touched; set_password /
verify_password are never called; nothing is written to ae00/ae01;
delete_device_data is never called. Cleanup: countdown stopped, screen powered
on, clock restored.

READOUT
-------
  * Per transition, the reclaim pair gives a direct yes/no on "does the SDK have
    to invalidate DIY mode after this mode?". Each YES is a mode whose feature
    namespace should call display.invalidate_diy_mode() itself, turning
    undocumented caller knowledge into driver behavior.
  * If EVERY mode needs re-entry, the answer is simpler and better: invalidate
    unconditionally whenever any non-frame command goes out, and delete the
    per-mode question entirely.
  * If NO mode needs re-entry, the 2026-07-20 text incident was something else
    (a race, or text specifically), and invalidate_diy_mode's docstring is
    overclaiming.
  * Graffiti painting through onto a NATIVE clock (sequence 2) => graffiti does
    not require DIY mode and is the safe delta path from any state, which is
    what the daemon already assumes. Graffiti NOT painting through => that
    assumption is wrong and the 2026-07-20 incident report needs correcting.
  * Chronograph commands moving a PAUSED countdown's display (sequence 4) =>
    the two features share one device-side timer, and the SDK must document that
    countdown.stop() is mandatory before any chronograph use.
  * Commands acked while the screen is OFF (sequence 5) => an ack means "frame
    received", never "pixels changed", and every probe that used an ack as proof
    of a visual result needs re-reading.

RESULT (2026-07-27): PARTIAL. This probe ran, but a verified, attributed
per-sequence readout (which reclaim pairs landed RED vs. GREEN, whether the
paused-countdown/chronograph hijack reproduced under sequence 4, and whether
graffiti painted through onto the native clock in sequence 2) is not
recorded in this pass. Do not infer specific per-mode invalidate_diy_mode()
requirements from this entry -- the five-sequence state machine
(docs/PROBE_PLAN.md P12) stays an open question pending a session that
records the operator's colour/count readout for each reclaim pair. The one
thing this run's design does establish independent of the operator's
readout is methodological: command verification was held off for the whole
run specifically so a nack could not raise CommandRejectedError and end a
sequence early, and the ack list was never cleared mid-run -- so, whatever
the visual verdicts turn out to be, they are not at risk of the same
ack-instrumentation bug that produced the retracted 2026-07-26 findings
elsewhere tonight.
"""

import asyncio
import io
import random
import time
from pathlib import Path

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

# Longer than the ~4.3 s worst-case ack latency measured on this panel
# (probes/probe_effect_speed_sweep.py). Acks are read only after this.
SETTLE_SECONDS = 6.0
WATCH_SECONDS = 10.0
LABEL_SECONDS = 4.0

# The run-start marker: scoreboard 0 | 0, then a short clock gap before sequence
# 1's own label. The operator reported not knowing the run had started and not
# being sure the first label they saw was really sequence 1. The clock gap is
# what separates the two -- without it, 0 | 0 and 1 | 0 four seconds apart read
# as one flickering label rather than two distinct events.
START_MARKER_SECONDS = 5.0
START_MARKER_GAP_SECONDS = 2.0

# The repo's own test font -- the package bundles none, and text.show requires a
# real TTF/OTF path. Resolved from this file so the probe works from any cwd; if
# it is missing the text step is skipped rather than crashing the sequence.
FONT_PATH = Path(__file__).resolve().parent.parent / "tests" / "Rain-DRM3.otf"

# The reclaim-pair convention, identical in every sequence (see the module
# docstring): RED = the naive attempt, GREEN = the forced-re-entry attempt.
NAIVE_COLOR = (220, 0, 0)
FORCED_COLOR = (0, 200, 0)
# Baseline frames that open a sequence, and must always land -- they are sent
# after an explicit invalidate, so a failure here is a probe/hardware problem
# rather than a state-machine result.
BASELINE_COLOR = (0, 60, 220)

# The app's 7-color effect palette from the 2026-07-25 HCI capture, byte-order
# identical to probes/probe_effect_speed_sweep.py.
APP_EFFECT_COLORS = bytes.fromhex("7f0000" "7f5100" "7f7f00" "007f00" "00007f" "7f007f" "7f7f7f")
APP_EFFECT_FRAME = bytearray([0x1C, 0x00, 0x03, 0x02, 0x00, 100, 0x07]) + APP_EFFECT_COLORS

STATUS_NAMES = {
    STATUS_FAILED: "FAILED/doomed",
    STATUS_NEXT_CHUNK: "NEXT_CHUNK",
    STATUS_SAVED: "SAVED",
}


def describe(ack: DeviceAck | StatusAck) -> str:
    """One-line rendering that names the status vocabulary rather than the raw int.

    A StatusAck is never a rejection -- reading status=3 SAVED as a nack is the
    misparse that shipped three broken features (protocol/response.py) -- so the
    two ack families are spelled differently here on purpose.
    """
    key = f"type={ack.command_type} subtype={ack.command_subtype}"
    if isinstance(ack, StatusAck):
        name = STATUS_NAMES.get(ack.status, f"UNRECOGNIZED({ack.status})")
        return f"StatusAck {key} status={ack.status} {name}  raw={ack.raw.hex(' ')}"
    verdict = "ACCEPTED" if ack.accepted else "*** REJECTED ***"
    return f"DeviceAck {key} {verdict}  raw={ack.raw.hex(' ')}"


def make_frame(base: tuple[int, int, int], sequence: int) -> bytes:
    """A 32x32 RGB frame: solid `base`, N counting blocks on top, anchor bottom-left.

    ASYMMETRIC BY CONSTRUCTION, and deliberately not a plain solid colour. The N
    white 3x3 blocks along the top edge (N = sequence number) identify WHICH
    sequence painted the frame, so a leftover frame from an earlier sequence is
    read as stale instead of fresh. The single anchor block in the bottom-left
    corner fixes orientation: rotate the panel 180 degrees and the counting row
    drops to the bottom while the anchor jumps to the top-right, which no
    symmetric pattern would reveal.
    """
    pixels = bytearray(bytes(base) * (32 * 32))

    def paint_block(left: int, top: int) -> None:
        for y in range(top, top + 3):
            for x in range(left, left + 3):
                offset = (y * 32 + x) * 3
                pixels[offset:offset + 3] = b"\xff\xff\xff"

    for index in range(sequence):
        paint_block(1 + index * 4, 1)  # counting row, top edge
    paint_block(1, 28)                 # orientation anchor, bottom-left
    return bytes(pixels)


def make_noise_gif(seed: int, frames: int = 8) -> bytes:
    """A 32x32 noise GIF, deterministic in `seed`. ~11 KB -> 3 outer chunks.

    Noise rather than a pattern so it compresses badly and the upload is a real
    multi-chunk transfer. The seed must be novel per upload: identical bytes
    hit the device's single-slot CRC and short-circuit to SAVED without a real
    transfer (GifFeature.activate_stored's fast path).
    """
    rng = random.Random(seed)
    images = []
    for _ in range(frames):
        im = Image.new("RGB", (32, 32), (0, 0, 0))
        px = im.load()
        for _ in range(300):
            px[rng.randrange(32), rng.randrange(32)] = (
                rng.randrange(256), rng.randrange(256), rng.randrange(256)
            )
        images.append(im)
    buf = io.BytesIO()
    images[0].save(buf, format="GIF", save_all=True, append_images=images[1:], duration=150, loop=0)
    return buf.getvalue()


def graffiti_dots() -> list[tuple[int, int]]:
    """An asymmetric dot cluster: a short diagonal plus one isolated pixel.

    Asymmetric on both axes so "graffiti painted through" can be told apart from
    "the panel happened to already have white pixels there", and so a flipped
    render is visible.
    """
    return [(x, x) for x in range(4, 16)] + [(28, 4), (27, 4), (28, 5)]


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        # NEVER cleared. Each step reports the slice from its own start index, so
        # a late ack lands in a later step's report instead of being destroyed --
        # the failure that voided probe_effect_length_byte2.py's headline finding.
        acks: list[tuple[float, DeviceAck | StatusAck]] = []
        unsubscribe = client.add_response_listener(lambda a: acks.append((time.perf_counter(), a)))

        # Fire-and-forget for the whole run: a nack must not raise
        # CommandRejectedError and end a sequence early (sequence 5 sends
        # commands to a powered-off screen and may well draw one).
        client.set_command_verification(False)

        async def step(label: str, send, watch: str, watch_seconds: float = WATCH_SECONDS) -> None:
            """Send one command, let acks SETTLE, report them, then watch.

            The only reporting discipline this probe allows: mark, send, wait
            SETTLE_SECONDS, read the slice. Never read before the wait; never
            clear the list.
            """
            print(f"\n  -- {label}", flush=True)
            mark = len(acks)
            t_send = time.perf_counter()
            try:
                await send()
            except Exception as ex:
                print(f"     SEND FAILED: {ex!r} (continuing)", flush=True)
            t_written = time.perf_counter()
            print(f"     write completed in {t_written - t_send:.3f}s;"
                  f" letting acks settle {SETTLE_SECONDS:.0f}s ...", flush=True)

            await asyncio.sleep(SETTLE_SECONDS)
            window = acks[mark:]
            if window:
                print(f"     {len(window)} ack(s):", flush=True)
                for t, ack in window:
                    print(f"       +{t - t_written:6.3f}s after write  {describe(ack)}", flush=True)
            else:
                # Silence after a full settle window is a RESULT (fire-and-forget),
                # not a failure -- graffiti is already known to be ack-silent.
                print(f"     NO ACKS in {SETTLE_SECONDS:.0f}s -- record as silent, not as broken",
                      flush=True)

            print(f"     WATCH: {watch}", flush=True)
            remaining = watch_seconds - SETTLE_SECONDS
            if remaining > 0:
                await asyncio.sleep(remaining)

        async def reclaim_pair(sequence: int, after: str) -> None:
            """The two-frame test that makes "is DIY re-entry required?" visible.

            Attempt A is what an unaware caller writes. Attempt B forces the
            mode-1 entry. Which window the panel changes in IS the answer.
            """
            print(f"\n  ### RECLAIM PAIR after {after} -- RED = no re-entry, GREEN = re-entry forced",
                  flush=True)
            await step(
                f"seq {sequence} attempt A (NAIVE): show_frame, NO invalidate_diy_mode",
                lambda: client.display.show_frame(make_frame(NAIVE_COLOR, sequence)),
                f"does the panel turn RED with {sequence} white block(s) on top?"
                f" RED => no DIY re-entry needed after {after}."
                f" Still showing {after} => re-entry IS needed; keep watching attempt B.",
            )

            def forced() -> object:
                # The panel left DIY mode device-side when the native command
                # above ran, but the driver cannot see feature-namespace
                # commands, so its flag still says "in DIY" -- exactly the
                # 2026-07-20 swallowed-reclaim condition. This is the call the
                # embedder currently has to know to make.
                client.display.invalidate_diy_mode()
                return client.display.show_frame(make_frame(FORCED_COLOR, sequence))

            await step(
                f"seq {sequence} attempt B (FORCED): invalidate_diy_mode + show_frame",
                forced,
                f"does the panel turn GREEN with {sequence} white block(s) on top?"
                f" GREEN after a RED-less window A => re-entry is REQUIRED after {after}."
                f" Neither colour ever appears => the reclaim path is broken for {after}"
                f" (a bigger finding -- record it prominently).",
            )

        async def run_start_marker() -> None:
            """Panel says 0 | 0: the run has begun and the NEXT label is sequence 1.

            Shown ONCE, before sequence 1's label and therefore before any step of
            any sequence, so it can never sit inside a transition under test.
            """
            print("\n" + "#" * 78, flush=True)
            print(f"# RUN START MARKER -- panel shows scoreboard 0 | 0 for {START_MARKER_SECONDS:.0f}s,",
                  flush=True)
            print(f"# then the clock for {START_MARKER_GAP_SECONDS:.0f}s, then the SEQUENCE 1 label"
                  f" (1 | 0).", flush=True)
            print("# 0 is reserved for this marker; no sequence uses it.", flush=True)
            print("#" * 78, flush=True)
            try:
                await client.scoreboard.show(0, 0)
                await asyncio.sleep(START_MARKER_SECONDS)
                # The gap exists so 0 | 0 and 1 | 0 read as two events, not one.
                await client.clock.show()
                await asyncio.sleep(START_MARKER_GAP_SECONDS)
            except Exception as ex:
                print(f"  start marker FAILED (continuing): {ex!r}", flush=True)

        async def sequence_label(number: int, title: str) -> None:
            """The ONLY panel label a sequence gets, held before its first step.

            Never called between steps and never before a reclaim pair: the
            scoreboard is a native-mode command, so a label inside a sequence
            would become part of the transition being measured and would change
            the reclaim pair's question from "after TEXT" to "after SCOREBOARD".
            """
            print(f"\n{'=' * 78}\n=== SEQUENCE {number}: {title}", flush=True)
            print(f"=== PANEL LABEL: scoreboard {number} | 0, held {LABEL_SECONDS:.0f}s. Everything"
                  f" after it, until the", flush=True)
            print(f"=== next label, is sequence {number}. No further labels appear inside it.", flush=True)
            print("=" * 78, flush=True)
            try:
                await client.scoreboard.show(number, 0)
                await asyncio.sleep(LABEL_SECONDS)
            except Exception as ex:
                print(f"  label FAILED (continuing): {ex!r}", flush=True)

        # Known-state entry: reset (04 00 03 80, non-destructive), settle, clock.
        try:
            print("resetting device to a known state ...", flush=True)
            await client.common.reset()
            await asyncio.sleep(4)
            await client.common.turn_on()
            await client.common.set_brightness(60)
            await client.clock.show()
            await asyncio.sleep(3)
            print(f"baseline: screen on, brightness 60, clock. {len(acks)} ack(s) logged"
                  f" (kept, never cleared).", flush=True)
        except Exception as ex:
            print(f"  reset/clock baseline FAILED: {ex!r}", flush=True)

        await run_start_marker()

        # ================= SEQUENCE 1: DIY frame -> text -> full frame =========
        try:
            await sequence_label(1, "DIY frame -> text -> full frame")

            def baseline_frame(sequence: int) -> object:
                client.display.invalidate_diy_mode()
                return client.display.show_frame(make_frame(BASELINE_COLOR, sequence))

            await step(
                "seq 1 step 1: DIY baseline frame (forced entry -- this MUST land)",
                lambda: baseline_frame(1),
                "the 1 | 0 label should be REPLACED by BLUE with 1 white block on top and"
                " the bottom-left anchor. Still showing 1 | 0 => the frame never rendered;"
                " stop, because the probe's own baseline is broken.",
            )
            if FONT_PATH.exists():
                await step(
                    "seq 1 step 2: native text takeover -- the 2026-07-20 incident's mode",
                    lambda: client.text.show("P12", str(FONT_PATH), font_size=16),
                    "scrolling text should replace the blue frame entirely.",
                )
            else:
                print(f"\n  -- seq 1 step 2 SKIPPED: no font at {FONT_PATH}", flush=True)
            await reclaim_pair(1, "TEXT")
        except Exception as ex:
            print(f"SEQUENCE 1 FAILED: {ex!r}", flush=True)

        # ======== SEQUENCE 2: DIY frame -> clock -> graffiti -> full frame =====
        try:
            await sequence_label(2, "DIY frame -> clock -> graffiti -> full frame")

            def baseline_frame_2() -> object:
                client.display.invalidate_diy_mode()
                return client.display.show_frame(make_frame(BASELINE_COLOR, 2))

            await step(
                "seq 2 step 1: DIY baseline frame (forced entry)",
                baseline_frame_2,
                "the 2 | 0 label should be REPLACED by BLUE with 2 white blocks on top."
                " Still showing 2 | 0 => the frame never rendered.",
            )
            await step(
                "seq 2 step 2: native clock",
                lambda: client.clock.show(),
                "clock should replace the blue frame.",
            )
            await step(
                "seq 2 step 3: graffiti onto the NATIVE clock (graffiti is ack-silent by design)",
                lambda: client.graffiti.set_pixels((255, 255, 255), graffiti_dots()),
                "do white pixels appear OVER the running clock -- a diagonal from"
                " upper-left plus a 3-pixel corner mark near the top-right?"
                " YES => graffiti needs no DIY mode and is the safe delta path from any"
                " state. NO => the daemon's delta assumption is wrong.",
            )
            await reclaim_pair(2, "CLOCK + GRAFFITI")
        except Exception as ex:
            print(f"SEQUENCE 2 FAILED: {ex!r}", flush=True)

        # ============== SEQUENCE 3: GIF -> effect -> DIY frame =================
        try:
            await sequence_label(3, "GIF -> effect -> DIY frame")
            # Novel seed per run: identical bytes would hit the single-slot CRC
            # and short-circuit instead of performing a real upload.
            gif_seed = int(time.time())
            await step(
                "seq 3 step 1: GIF upload (chunked, 3-way StatusAck handshake)",
                lambda: client.gif.upload_bytes(make_noise_gif(gif_seed)),
                "the 3 | 0 label should be REPLACED by animated colour noise."
                " Still showing 3 | 0 => the GIF never took over from the scoreboard,"
                " and everything later in this sequence is measuring the wrong entry"
                " state -- say so rather than rating the reclaim pair.",
                watch_seconds=12.0,
            )
            await step(
                "seq 3 step 2: effect, the app-exact captured frame (type 3 subtype 2)",
                lambda: client.effect._send(APP_EFFECT_FRAME, verify=False),
                "the effect should replace the GIF.",
            )
            # O-27 (2026-07-17): DIY entry mode 3 does NOT reliably take over an
            # EFFECT state. BleDisplay defaults to clear=True (mode 1), which is
            # the entry hardware-proven to always take -- so attempt B here is
            # also a direct test of that claim's strongest case.
            await reclaim_pair(3, "GIF + EFFECT")
        except Exception as ex:
            print(f"SEQUENCE 3 FAILED: {ex!r}", flush=True)

        # ===== SEQUENCE 4: clock -> countdown -> chronograph -> clock ==========
        # The P7 branch: a PAUSED countdown has been seen to hijack chronograph
        # commands. Arm, tick, pause, then send the whole chronograph vocabulary.
        try:
            await sequence_label(4, "clock -> countdown -> chronograph -> clock (P7 paused-countdown branch)")
            await step(
                "seq 4 step 1: clock",
                lambda: client.clock.show(),
                "the 4 | 0 label should be REPLACED by the running clock."
                " Still showing 4 | 0 => the clock command never took.",
            )
            await step(
                "seq 4 step 2: countdown.start(5, 0) -- arm a 5-minute countdown",
                lambda: client.countdown.start(5, 0),
                "a countdown should appear and TICK DOWN from about 05:00.",
            )
            await step(
                "seq 4 step 3: countdown.pause() -- the state that hijacks chronograph",
                lambda: client.countdown.pause(),
                "the countdown should FREEZE. Note the exact frozen value -- every"
                " chronograph step below is judged against it.",
            )
            for name, call, expectation in (
                ("chronograph.reset()", client.chronograph.reset,
                 "does the frozen countdown jump to 00:00, does a stopwatch appear, or nothing?"),
                ("chronograph.start()", client.chronograph.start,
                 "does anything start COUNTING UP, does the paused countdown RESUME"
                 " (the hijack), or nothing?"),
                ("chronograph.pause()", client.chronograph.pause,
                 "does whatever is running stop?"),
                ("chronograph.resume()", client.chronograph.resume,
                 "does it start again, and counting which way?"),
            ):
                await step(
                    f"seq 4 step 4: {name} against a PAUSED countdown",
                    call,
                    f"{expectation} Report the digits, not just 'it changed'.",
                )
            await step(
                "seq 4 step 5: countdown.stop() -- disarm, so the run leaves nothing armed",
                lambda: client.countdown.stop(),
                "the countdown/stopwatch should clear.",
            )
            await step(
                "seq 4 step 6: back to clock",
                lambda: client.clock.show(),
                "clock should return. If a timer is still visible, the device holds"
                " timer state the SDK cannot clear -- record that.",
            )
            await reclaim_pair(4, "CLOCK (after the timer branch)")
        except Exception as ex:
            print(f"SEQUENCE 4 FAILED: {ex!r}", flush=True)

        # ===== SEQUENCE 5: power off -> command -> power on -> full frame ======
        # SOFTWARE power only (common.build_set_power, [5 0 7 1 on]). Nothing is
        # unplugged and BLE stays connected the whole time -- that is the point.
        #
        # The label makes this sequence's PRIOR MODE exactly known: the screen
        # goes dark from scoreboard 5 | 0, not from whatever sequence 4 happened
        # to leave behind. That is an improvement -- step 4's "did the prior mode
        # resume?" outcome now has a specific value to look for -- but it does
        # mean the prior mode AND the sent-while-off command are both
        # scoreboards, so step 3 and step 4 name their digits explicitly.
        try:
            await sequence_label(5, "power off -> command -> power on -> full frame (software power)")
            await step(
                "seq 5 step 1: common.turn_off() -- screen off, BLE still connected",
                lambda: client.common.turn_off(),
                "the 5 | 0 label should go DARK. BLE stays up. Note that 5 | 0 is therefore"
                " the PRIOR MODE for step 4's readout -- it is what was on screen when the"
                " power went off.",
            )
            await step(
                "seq 5 step 2: brightness 40 sent to a POWERED-OFF screen -- acked?",
                lambda: client.common.set_brightness(40),
                "panel should stay dark. The ack line above is the result:"
                " an ack while off proves an ack means 'frame received', NEVER"
                " 'pixels changed'.",
            )
            await step(
                "seq 5 step 3: scoreboard 77 | 77 sent while OFF -- a MODE change in the dark",
                lambda: client.scoreboard.show(77, 77),
                "panel should stay dark. What matters is what appears at power-on."
                " 77 is chosen so this can never be confused with the 5 | 0 label:"
                " both are scoreboards, and only the digits tell them apart.",
            )
            await step(
                "seq 5 step 4: common.turn_on()",
                lambda: client.common.turn_on(),
                "WHICH comes back? READ THE DIGITS -- two of the three answers are"
                " scoreboards. 77 | 77 => commands sent while off DID execute,"
                " invisibly. 5 | 0 (this sequence's label, the mode in force when the"
                " screen went dark) => commands while off were dropped and the prior"
                " mode resumed. CLOCK => power-on resets to clock regardless.",
                watch_seconds=12.0,
            )
            await reclaim_pair(5, "POWER OFF/ON")
        except Exception as ex:
            print(f"SEQUENCE 5 FAILED: {ex!r}", flush=True)

        # ------------------------------------------------------------------ wrap-up
        print("\n" + "=" * 78, flush=True)
        print("verdict to record, per sequence:", flush=True)
        print("  RED landed in window A     => no DIY re-entry needed after that mode.", flush=True)
        print("  only GREEN landed          => re-entry REQUIRED; that mode's feature namespace", flush=True)
        print("                                should call display.invalidate_diy_mode() itself.", flush=True)
        print("  neither colour landed      => the reclaim path is broken for that mode. Bigger", flush=True)
        print("                                finding than the flag; record prominently.", flush=True)
        print("  ALL five need re-entry     => stop asking per-mode: invalidate unconditionally", flush=True)
        print("                                whenever any non-frame command goes out.", flush=True)
        print("  NONE need re-entry         => the 2026-07-20 swallowed-reclaim incident was not", flush=True)
        print("                                about DIY state, and invalidate_diy_mode's docstring", flush=True)
        print("                                overclaims.", flush=True)
        print("  chrono moved the PAUSED countdown => shared device-side timer; the SDK must", flush=True)
        print("                                document countdown.stop() before any chronograph use.", flush=True)
        print("  commands acked while OFF   => an ack is receipt, never a visual result. Re-read any", flush=True)
        print("                                probe that treated an ack as proof of rendering.", flush=True)
        print(f"\nfull ack log: {len(acks)} notification(s) captured across the whole run"
              f" (never cleared).", flush=True)

        # Cleanup: leave nothing armed, nothing dark.
        unsubscribe()
        try:
            await client.countdown.stop()
            await client.common.turn_on()
        except Exception as ex:
            print(f"cleanup (countdown/power) FAILED: {ex!r}", flush=True)
        await client.clock.show()
        print("countdown stopped, screen on, clock restored. done.", flush=True)


asyncio.run(main())
