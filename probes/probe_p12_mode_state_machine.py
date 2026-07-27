"""P12 -- does a full frame need a DIY re-entry after mode X? ONE SEQUENCE PER RUN.

WHY THIS PROBE WAS REBUILT
--------------------------
The first version ran five sequences back to back in one seven-minute
invocation: roughly twenty distinct visuals, each needing a judgement, with no
way for the operator to re-check anything. It ran twice on hardware and produced
usable data only for sequence 5, both times. Run 1 (no panel labels) was called
"a lab book probe". Run 2 (labels added) was called "a circus, nothing matched
to what you said".

The design was the fault, not the operator and not the labelling. It was the
third instance of the same mistake in one session -- P5's phase 3 failed
identically. A probe a remote observer cannot follow yields no data however
sound its protocol design is.

Two specific failures are fixed here:

  1. ONE SEQUENCE PER RUN, ~70 s, mandatory argument. One labelled baseline, one
     mode change, one two-colour reclaim pair. Nothing else reaches the panel.
     Re-running a sequence costs about a minute, so a missed observation is
     cheap to recover instead of unrecoverable.
  2. THE FULL VISUAL SCRIPT IS PRINTED AT STARTUP, before any BLE contact, and
     it is EXHAUSTIVE -- every visual in order, including the BLUE BASELINE
     FRAME. That omission is precisely what sank run 2: the operator was briefed
     on "RED = no re-entry, GREEN = re-entry" and the first thing they saw was
     blue, which contradicted the brief and discredited everything after it. The
     blue baseline was always in the design; it was never in the briefing. The
     console text below is the source the operator gets briefed from, so it is
     written to be read aloud literally.

THE QUESTION, UNCHANGED
-----------------------
After mode X, does the next full frame land on its own, or does it need a forced
DIY re-entry first? The hard evidence behind the question is a failure: on
2026-07-20 a native text takeover ended, the daemon sent its reclaim frame, and
the frame was SILENTLY SWALLOWED -- BleDisplay._diy_mode_enabled still said "we
are in DIY mode", so no DIY-entry command was sent, and a full frame sent into
text mode is dropped. Only a later periodic keyframe healed the panel. That is
why invalidate_diy_mode() exists, and knowing when to call it is currently
undocumented knowledge every embedder must somehow have.

Each run answers the question for exactly one mode, via the RECLAIM PAIR:

    attempt A (NAIVE)  -- show_frame() with NO invalidate_diy_mode(). What a
                          caller who does not know about DIY state would write.
                          Base colour RED.
    attempt B (FORCED) -- invalidate_diy_mode(), then show_frame(). Forces the
                          mode-1 entry that is hardware-proven to take from any
                          panel state. Base colour GREEN.

    RED appears   => NO re-entry needed after that mode.
    only GREEN    => RE-ENTRY IS REQUIRED after that mode.
    neither       => the reclaim path is broken for that mode -- a bigger
                     finding than the flag, and one no flag-fiddling fixes.
    GREEN in A    => impossible; the probe has a bug. Report it, record nothing.

Frames are asymmetric by construction: N white 3x3 blocks along the TOP edge
(N = the sequence number) plus one white 3x3 anchor in the BOTTOM-LEFT corner. A
frame left from another run shows the WRONG BLOCK COUNT, and a 180-degree
rotation moves the counting row to the bottom and the anchor to the top-right.
A plain solid colour would teach nothing, since a stale red and a fresh red look
identical.

THE FIVE SEQUENCES
------------------
    1  reclaim after TEXT
    2  reclaim after CLOCK + GRAFFITI  (plus its own graffiti observation)
    3  reclaim after GIF + EFFECT
    4  reclaim after the TIMER BRANCH
    5  reclaim after software POWER OFF/ON   <- known answer, validation case

SEQUENCE 5 IS ALREADY ANSWERED. KEEP IT, DO NOT RE-DERIVE IT.
Run 1 of the previous version returned GREEN: DIY RE-ENTRY IS REQUIRED after
turn_off/turn_on. The naive show_frame was silently swallowed WHILE STILL ACKING
ACCEPTED (05 00 00 00 01) -- an ack means the frame was received, never that
pixels changed. Corroborated the same night by P11: the DIY frame is the ONLY
state that does not survive a BLE reconnect or a software power cycle; every
native mode persists. Sequence 5 is retained as the validation case -- the run
that proves the apparatus still works. Any run of it that comes back RED means
this probe, not the device, has changed.

SEQUENCE 2 carries a second observation that matters on its own, so it gets its
own clearly described mark and its own watch window instead of being buried
mid-sequence: DO GRAFFITI PIXELS DRAW OVER A RUNNING CLOCK WITHOUT DIY MODE?
That is the daemon's entire delta-path assumption. If graffiti paints through
from a native state, deltas are safe from anywhere; if it does not, the daemon's
rendering model is wrong.

SEQUENCE 4 does NOT re-derive the countdown/chronograph semantics. Those are
settled: probes/probe_p7_odds_and_ends.py phases 3-8 got a clean readout -- the
countdown FROZE on pause, chronograph.start produced an INDEPENDENT stopwatch
counting up rather than hijacking the paused countdown, resume continued from
the frozen value, and reset zeroed it. This sequence walks the panel through
that branch only far enough to be genuinely "after the timer branch", then asks
the reclaim question. Cite P7 for the timer semantics, never this probe.

ACK DISCIPLINE
--------------
Acks are read only after SETTLE_SECONDS, the list is NEVER cleared -- each step
reports a slice from its own start index -- and every ack prints its wall-clock
delta from the send. This exists because on 2026-07-26 two probes printed ack
reports immediately after the write, before the reply arrived, then cleared the
list at the phase boundary; that produced the false finding "these frames are
never acked" and cost a hardware run.

SETTLE_SECONDS is 2.0. P14 (probes/probe_p14_ack_timing.py, run 2026-07-27)
measured the real numbers across 7 families and 55 notifications: no silent
family, post-write latency sub-50 ms, flat commands acking 0.13-0.30 s from send
start, a full DIY frame 0.6-0.9 s, and GIF chunk statuses interleaving with
later chunk writes. The earlier "~4.3 s worst case" figure was an artifact of a
4 s scoreboard hold being counted as latency, and is retired.

METHOD
------
Device reset (common.reset, 04 00 03 80 -- VERIFIED non-destructive, used live
2026-07-18 to clear a stuck state), settle, clock baseline. Command verification
is turned OFF for the whole run so a nack cannot raise CommandRejectedError and
end a run early -- acks still arrive through the response listener, which fires
regardless. Every step is wrapped so one failure cannot end the run. Nothing in
the `experimental` namespace is touched; set_password / verify_password are
never called; nothing is written to ae00/ae01; delete_device_data is never
called. Cleanup: any timer stopped, screen powered on, clock restored.

READOUT
-------
  * Each YES ("re-entry required") is a mode whose feature namespace should call
    display.invalidate_diy_mode() itself, turning undocumented caller knowledge
    into driver behavior.
  * If every mode needs re-entry, the answer is simpler and better: invalidate
    unconditionally whenever any non-frame command goes out, and delete the
    per-mode question entirely. Sequence 5 already says YES for power, and P11
    says the DIY frame is the only state that does not survive a reconnect --
    two independent pushes toward the unconditional rule.
  * If NO mode needs re-entry, the 2026-07-20 text incident was something else,
    and invalidate_diy_mode's docstring overclaims.
  * Graffiti painting through onto a NATIVE clock (sequence 2) => graffiti needs
    no DIY mode and is the safe delta path from any state, which is what the
    daemon already assumes. NOT painting through => that assumption is wrong.
  * A naive frame that ACKS ACCEPTED but never appears (already seen in sequence
    5) => an ack is receipt, never a visual result. Any probe that treated an
    ack as proof of rendering needs re-reading.

USAGE
-----
    python probes/probe_p12_mode_state_machine.py <1-5>

The sequence argument is MANDATORY and is validated before any BLE contact, so a
typo cannot half-run anything. Exactly one sequence runs per invocation; there is
no "all" mode, deliberately.

RESULT (2026-07-27): all five sequences run, one invocation each. HEADLINE: the
real question is not "does DIY mode need re-entry", it is "is a native mode
still actively drawing". A naive show_frame() is never rejected and never
silently swallowed at the protocol level -- it arrives, acks ACCEPTED, and
renders. What happens next depends on whether something else still owns the
framebuffer.

  * Sequence 1 (after TEXT): re-entry required. Operator: "red flicker
    (microsecond) -> P12 text (scrolling never stopped) -> Green". The naive
    frame DID render, then the still-running marquee scroll repainted over it
    on its next tick -- it lost a REPAINT RACE, not a silent swallow. The
    2026-07-20 incident's "silently swallowed while acking ACCEPTED"
    description is corrected on this point: not swallowed, outraced. The
    fix (invalidate_diy_mode before the reclaim) is unchanged.
  * Sequence 2 (after CLOCK + GRAFFITI): no re-entry needed -- both the naive
    red and the forced green held. SEPARATE RESULT, own finding: graffiti
    sent onto the running clock, no DIY mode, does NOT composite over it --
    operator: "nothing drew over each other and the clock stayed for a sec
    and switched". It forces a MODE SWITCH rather than drawing through, so
    the daemon's delta-path assumption (graffiti is safe from any state) is
    wrong as a blanket claim: it is safe only once the panel is already in
    the pixel/DIY framebuffer. Also observed: the native clock does take
    over cleanly from the blue DIY baseline, but holds only ~1s before the
    next command in the sequence lands.
  * Sequence 3 (after GIF + EFFECT): re-entry required, with a distinct
    footprint. Operator: "Red frame appeared and was then PUSHED DOWN by the
    rainbow effect, it literally DRAGGED THE FRAME DOWN and continued with
    the rainbow effect of falling." The effect operates on the LIVE
    framebuffer, not a private buffer -- it consumed the injected frame and
    transformed it into its own animation. Speculative, UNPROBED follow-up
    only (not a capability): content might be deliberately feedable to a
    running effect. Queued in docs/PROBE_PLAN.md.
  * Sequence 4 (after the TIMER BRANCH): re-entry required, with a third
    distinct footprint. The red frame stayed visible as a background while
    "the chrono's digits and the dot animation drew over red... I could see
    the digits changing", then it fully reverted; the timer never stopped
    counting. Native modes repaint only their own DIRTY REGIONS -- text takes
    the full width, the effect takes the whole buffer, the chronograph takes
    only its glyphs. One unidentified transient: a brief unreadable flicker
    between green and the clock at the end of this sequence -- logged as
    observed-and-unexplained, the third such this session, none reproduced.
  * Sequence 5 (after software POWER OFF/ON): no re-entry needed on this
    clean run -- blue DIY frame -> dark -> BLUE FRAME RESTORED -> RED landed
    at the naive attempt -> green. This CONTRADICTS the "known answer" this
    docstring opens with (GREEN, 2026-07-26): that earlier run needed green
    only because it had also sent a scoreboard 77|77 command while the panel
    was dark, which executed invisibly and left a NATIVE MODE live at
    power-on, forcing the reclaim. Re-entry tracks whether a native mode is
    actively live, not power-cycling itself -- the module's "SEQUENCE 5 IS
    ALREADY ANSWERED" framing above is superseded by this result and should
    not be treated as settled without accounting for it.
"""

import asyncio
import io
import random
import sys
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

# P14 (2026-07-27) measured post-write ack latency at sub-50 ms, flat commands at
# 0.13-0.30 s from send start and a full DIY frame at 0.6-0.9 s. 2 s is a wide
# margin over the slowest of those and keeps every run under 90 s.
SETTLE_SECONDS = 2.0
WATCH_SECONDS = 10.0
LABEL_SECONDS = 4.0

# The repo's own test font -- the package bundles none, and text.show requires a
# real TTF/OTF path. Resolved from this file so the probe works from any cwd.
FONT_PATH = Path(__file__).resolve().parent.parent / "tests" / "Rain-DRM3.otf"

# The reclaim-pair convention: RED = naive attempt, GREEN = forced re-entry.
NAIVE_COLOR = (220, 0, 0)
FORCED_COLOR = (0, 200, 0)
# The baseline frame that opens every run. Sent after an explicit invalidate, so
# it must always land -- and the operator MUST be told to expect it, which is
# what the startup script exists for.
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

SEQUENCE_TITLES = {
    1: "reclaim after TEXT",
    2: "reclaim after CLOCK + GRAFFITI (plus the graffiti-over-clock observation)",
    3: "reclaim after GIF + EFFECT",
    4: "reclaim after the TIMER BRANCH (timer semantics already settled by P7)",
    5: "reclaim after software POWER OFF/ON  [KNOWN ANSWER: GREEN -- validation case]",
}

# The middle of each run's visual script: what replaces the blue baseline, in
# order, before the reclaim pair. Written to be read to the operator verbatim --
# literal colours and shapes, no shorthand.
SEQUENCE_VISUALS = {
    1: (
        'SCROLLING TEXT reading "P12" replaces the blue frame. ~10 s.'
        " This is the mode whose reclaim we are testing.",
    ),
    2: (
        "The CLOCK replaces the blue frame -- normal time display, ticking. ~10 s.",
        "WHITE PIXELS are drawn ON TOP of the still-running clock: a 12-pixel"
        " DIAGONAL line from the upper-left going down and to the right, PLUS a"
        " small 3-pixel hook near the TOP-RIGHT corner. ~12 s."
        " THIS IS ITS OWN RESULT, report it separately: white marks appear over a"
        " clock that keeps ticking => graffiti needs no DIY mode and the daemon's"
        " delta path is safe from any state. Nothing appears => that assumption is"
        " wrong. (Graffiti sends no ack at all, by design -- console silence here"
        " is expected and is not a failure.)",
    ),
    3: (
        "ANIMATED COLOUR NOISE (a GIF) replaces the blue frame. ~14 s, including"
        " several seconds of upload during which the blue frame may simply"
        " persist -- that is the transfer, not a failure.",
        "A COLOUR EFFECT -- a moving multi-colour pattern -- replaces the noise. ~10 s.",
    ),
    4: (
        "A COUNTDOWN appears and TICKS DOWN from about 05:00. ~10 s.",
        "The countdown FREEZES, then a STOPWATCH starts COUNTING UP from 00:00."
        " ~10 s. This matches P7 and is expected -- the stopwatch is INDEPENDENT"
        " of the paused countdown, not a hijack of it. Nothing here needs judging;"
        " the run only needs the panel to have been through the timer branch.",
    ),
    5: (
        "The panel goes COMPLETELY DARK (software power off; BLE stays"
        " connected). ~10 s.",
        "The panel comes back on. ~10 s. Per P11 the blue frame will NOT return --"
        " native modes survive a power cycle but a DIY frame does not -- so expect"
        " the clock or the last native mode, not blue.",
    ),
}


def print_usage() -> None:
    print("usage: python probes/probe_p12_mode_state_machine.py <1-5>", flush=True)
    print("", flush=True)
    print("Runs exactly ONE sequence, ~70 s. The argument is mandatory.", flush=True)
    for number, title in SEQUENCE_TITLES.items():
        print(f"    {number}   {title}", flush=True)


def select_sequence(argv: list[str]) -> int:
    """Which sequence to run, from the command line. Validated before any BLE contact.

    Mandatory and single-valued on purpose: the multi-sequence version of this
    probe was unfollowable, and there is deliberately no "run all" mode.
    """
    if not argv:
        print("error: a sequence number is required.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    if len(argv) > 1:
        print(f"error: expected exactly one sequence number, got {len(argv)}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    try:
        sequence = int(argv[0])
    except ValueError:
        sequence = -1
    if sequence not in SEQUENCE_TITLES:
        print(f"error: unrecognized sequence {argv[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    return sequence


def print_visual_script(sequence: int) -> None:
    """The COMPLETE ordered list of everything the operator will see, before BLE.

    Exhaustive on purpose. The previous version briefed "RED = no re-entry,
    GREEN = re-entry" and never mentioned the blue baseline frame that opens
    every run -- so the first thing the operator saw contradicted their brief and
    discredited the whole run. Every visual is listed here, including the ones
    that are merely setup, with the colour named and what replaces it.
    """
    blocks = "block" if sequence == 1 else "blocks"
    visuals = [
        "The CLOCK, for a few seconds. Start-up baseline after a device reset."
        " Nothing to judge.",
        f"A SCOREBOARD reading  {sequence} | 0  for {LABEL_SECONDS:.0f} s. This is the run's"
        f" label: it confirms sequence {sequence} is what is running. It is the only"
        f" label all run.",
        f"*** A SOLID BLUE FRAME *** with {sequence} white {blocks} along the TOP edge and one"
        f" white block in the BOTTOM-LEFT corner. ~10 s. EXPECT THIS -- it is the"
        f" baseline every run opens with, it is NOT part of the red/green test, and it"
        f" is not an error. If it does not appear, the run is broken before it starts:"
        f" say so and stop.",
    ]
    visuals.extend(SEQUENCE_VISUALS[sequence])
    visuals.extend([
        f"*** ATTEMPT A *** A SOLID RED FRAME with the same {sequence} white {blocks} on top."
        f" ~10 s. THE FIRST THING TO REPORT: does the panel actually turn RED, or does"
        f" it stay on the previous visual?",
        f"*** ATTEMPT B *** A SOLID GREEN FRAME with the same {sequence} white {blocks} on"
        f" top. ~10 s. THE SECOND THING TO REPORT: does the panel turn GREEN?",
        "The CLOCK returns. Cleanup, nothing to judge.",
    ])

    print("=" * 78, flush=True)
    print(f"P12 SEQUENCE {sequence}: {SEQUENCE_TITLES[sequence]}", flush=True)
    print("=" * 78, flush=True)
    print("EVERYTHING YOU WILL SEE, IN ORDER -- read this before the run starts:", flush=True)
    print("", flush=True)
    for index, visual in enumerate(visuals, start=1):
        print(f"  {index}. {visual}", flush=True)
    print("", flush=True)
    print("WHAT THE ANSWER MEANS:", flush=True)
    print("  RED appeared at attempt A     => NO DIY re-entry needed after this mode.", flush=True)
    print("  RED never came, GREEN did     => DIY RE-ENTRY IS REQUIRED after this mode.", flush=True)
    print("  neither RED nor GREEN         => the reclaim path is broken for this mode.", flush=True)
    print("                                   Bigger finding; record it prominently.", flush=True)
    print("  GREEN appeared at attempt A   => impossible. The probe has a bug -- report", flush=True)
    print("                                   that, and record no result.", flush=True)
    if sequence == 2:
        print("", flush=True)
        print("  SEQUENCE 2 HAS A SECOND, SEPARATE RESULT: whether the white diagonal and", flush=True)
        print("  corner hook appear over the running clock (visual 5). Report it even if", flush=True)
        print("  the red/green part is inconclusive -- it stands on its own.", flush=True)
    if sequence == 5:
        print("", flush=True)
        print("  SEQUENCE 5 IS THE VALIDATION CASE. The answer is already known to be", flush=True)
        print("  GREEN (2026-07-26, corroborated by P11). If this run comes back RED, the", flush=True)
        print("  probe has changed, not the device -- do not record a new finding.", flush=True)
    print("=" * 78, flush=True)
    print("", flush=True)


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
    white 3x3 blocks along the top edge (N = sequence number) identify WHICH run
    painted the frame, so a leftover frame from another run reads as stale
    instead of fresh. The single anchor block in the bottom-left corner fixes
    orientation: rotate the panel 180 degrees and the counting row drops to the
    bottom while the anchor jumps to the top-right, which no symmetric pattern
    would reveal.
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
    multi-chunk transfer. The seed must be novel per upload: identical bytes hit
    the device's single-slot CRC and short-circuit to SAVED without a real
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
    """A 12-pixel diagonal from the upper-left plus a 3-pixel hook near the top-right.

    Asymmetric on both axes so "graffiti painted through" can be told apart from
    "the clock happened to have white pixels there", and so a flipped render is
    visible. The startup script describes it to the operator in exactly these
    terms -- keep the two in sync if this changes.
    """
    return [(x, x) for x in range(4, 16)] + [(28, 4), (27, 4), (28, 5)]


async def main(sequence: int) -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        # NEVER cleared. Each step reports the slice from its own start index, so
        # a late ack lands in a later step's report instead of being destroyed --
        # the failure that voided probe_effect_length_byte2.py's headline finding.
        acks: list[tuple[float, DeviceAck | StatusAck]] = []
        unsubscribe = client.add_response_listener(lambda a: acks.append((time.perf_counter(), a)))

        # Fire-and-forget for the whole run: a nack must not raise
        # CommandRejectedError and end the run early.
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

            await asyncio.sleep(SETTLE_SECONDS)
            window = acks[mark:]
            print(f"     write completed in {t_written - t_send:.3f}s; {len(window)} ack(s)"
                  f" in the {SETTLE_SECONDS:.0f}s settle window:", flush=True)
            for t, ack in window:
                print(f"       +{t - t_written:6.3f}s after write  {describe(ack)}", flush=True)
            if not window:
                # Silence after a full settle window is a RESULT, not a failure --
                # graffiti is ack-silent by design, and P14 found no other silent
                # family, so silence anywhere else is worth noticing.
                print("       (none -- record as silent, not as broken)", flush=True)

            print(f"     WATCH: {watch}", flush=True)
            remaining = watch_seconds - SETTLE_SECONDS
            if remaining > 0:
                await asyncio.sleep(remaining)

        async def reclaim_pair(after: str) -> None:
            """The two-frame test that makes "is DIY re-entry required?" visible."""
            print(f"\n  ### RECLAIM PAIR after {after} -- RED = no re-entry, GREEN = re-entry forced",
                  flush=True)
            await step(
                f"ATTEMPT A (NAIVE): show_frame after {after}, NO invalidate_diy_mode",
                lambda: client.display.show_frame(make_frame(NAIVE_COLOR, sequence)),
                f"does the panel turn RED? RED => no DIY re-entry needed after {after}."
                f" Still showing the previous visual => re-entry IS needed; keep watching"
                f" attempt B. NOTE: this frame may ACK ACCEPTED and still never appear --"
                f" that has already been seen once, so the ack line above is not the answer.",
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
                f"ATTEMPT B (FORCED): invalidate_diy_mode + show_frame after {after}",
                forced,
                f"does the panel turn GREEN? GREEN after a RED-less window A => re-entry"
                f" is REQUIRED after {after}. Neither colour ever appeared => the reclaim"
                f" path is broken for {after} -- record that prominently.",
            )

        # Known-state entry: reset (04 00 03 80, non-destructive), settle, clock.
        try:
            print("resetting device to a known state ...", flush=True)
            await client.common.reset()
            await asyncio.sleep(3)
            await client.common.turn_on()
            await client.common.set_brightness(60)
            await client.clock.show()
            await asyncio.sleep(3)
            print("baseline: screen on, brightness 60, clock. (visual 1)", flush=True)
        except Exception as ex:
            print(f"  reset/clock baseline FAILED: {ex!r}", flush=True)

        # The run's one and only panel label, before the first step. The
        # scoreboard is itself a native-mode command, so no further label is
        # shown: one placed between steps would become part of the transition
        # under test, and one placed before the reclaim pair would change the
        # question from "after TEXT" to "after SCOREBOARD".
        print(f"\n=== PANEL LABEL (visual 2): scoreboard {sequence} | 0, held"
              f" {LABEL_SECONDS:.0f}s. No further labels this run.", flush=True)
        try:
            await client.scoreboard.show(sequence, 0)
            await asyncio.sleep(LABEL_SECONDS)
        except Exception as ex:
            print(f"  label FAILED (continuing): {ex!r}", flush=True)

        # The blue baseline every run opens with -- forced entry, so it is
        # independent of whatever the panel was doing beforehand.
        def baseline_frame() -> object:
            client.display.invalidate_diy_mode()
            return client.display.show_frame(make_frame(BASELINE_COLOR, sequence))

        await step(
            "BASELINE (visual 3): blue DIY frame, forced entry",
            baseline_frame,
            f"the {sequence} | 0 label should be REPLACED by a SOLID BLUE frame with"
            f" {sequence} white block(s) on the top edge and one in the bottom-left."
            f" THIS IS EXPECTED AND IS NOT THE RED/GREEN TEST. Still showing the"
            f" scoreboard => the baseline frame never rendered; stop, the run is broken"
            f" before it starts.",
        )

        # ---------------------------------------------------------------- modes
        if sequence == 1:
            if FONT_PATH.exists():
                await step(
                    "MODE (visual 4): native text takeover -- the 2026-07-20 incident's mode",
                    lambda: client.text.show("P12", str(FONT_PATH), font_size=16),
                    'scrolling text reading "P12" should replace the blue frame.',
                )
            else:
                print(f"\n  -- MODE STEP SKIPPED: no font at {FONT_PATH}. The reclaim below"
                      f" would measure the BASELINE, not TEXT -- abandon this run and"
                      f" supply a font.", flush=True)
            await reclaim_pair("TEXT")

        elif sequence == 2:
            await step(
                "MODE (visual 4): native clock",
                lambda: client.clock.show(),
                "the clock should replace the blue frame.",
            )
            await step(
                "OBSERVATION (visual 5, its own result): graffiti onto the RUNNING clock,"
                " no DIY mode",
                lambda: client.graffiti.set_pixels((255, 255, 255), graffiti_dots()),
                "do WHITE PIXELS appear ON TOP of the still-ticking clock -- a 12-pixel"
                " DIAGONAL from the upper-left going down-right, PLUS a 3-pixel hook near"
                " the TOP-RIGHT corner? YES => graffiti needs no DIY mode and the daemon's"
                " delta path is safe from any state. NO => that assumption is wrong and the"
                " daemon's rendering model needs revisiting. Graffiti is ack-silent by"
                " design, so no ack above is expected and is not a failure.",
                watch_seconds=12.0,
            )
            await reclaim_pair("CLOCK + GRAFFITI")

        elif sequence == 3:
            # Novel seed per run: identical bytes would hit the single-slot CRC
            # and short-circuit instead of performing a real upload.
            gif_seed = int(time.time())
            await step(
                "MODE 1 of 2 (visual 4): GIF upload (chunked, 3-way StatusAck handshake)",
                lambda: client.gif.upload_bytes(make_noise_gif(gif_seed)),
                "animated colour noise should replace the blue frame. The blue frame may"
                " persist for several seconds during the upload -- that is the transfer,"
                " not a failure.",
                watch_seconds=14.0,
            )
            await step(
                "MODE 2 of 2 (visual 5): effect, the app-exact captured frame (type 3 subtype 2)",
                lambda: client.effect._send(APP_EFFECT_FRAME, verify=False),
                "a moving multi-colour effect should replace the noise.",
            )
            # O-27 (2026-07-17): DIY entry mode 3 does NOT reliably take over an
            # EFFECT state. BleDisplay defaults to clear=True (mode 1), the entry
            # hardware-proven to always take -- so attempt B is also a direct
            # test of that claim's strongest case.
            await reclaim_pair("GIF + EFFECT")

        elif sequence == 4:
            # Timer SEMANTICS are settled -- probe_p7_odds_and_ends.py phases 3-8:
            # countdown froze on pause, chronograph.start produced an INDEPENDENT
            # stopwatch counting up (not a hijack), resume continued from the
            # frozen value, reset zeroed it. Nothing here re-derives that. These
            # two steps exist only to put the panel genuinely through the timer
            # branch before the reclaim question is asked.
            await step(
                "MODE 1 of 2 (visual 4): countdown.start(5, 0) -- enter the timer branch",
                lambda: client.countdown.start(5, 0),
                "a countdown should appear and tick down from about 05:00. Nothing to"
                " judge -- P7 already characterized this.",
            )

            async def pause_then_chronograph() -> None:
                await client.countdown.pause()
                await asyncio.sleep(1)
                await client.chronograph.start()

            await step(
                "MODE 2 of 2 (visual 5): countdown.pause() then chronograph.start()"
                " -- the P7-verified pair",
                pause_then_chronograph,
                "the countdown should freeze and an INDEPENDENT stopwatch should count up."
                " Expected, per P7 -- nothing to judge. The run only needs the panel to"
                " have been through the timer branch.",
            )
            await reclaim_pair("TIMER BRANCH")

        elif sequence == 5:
            await step(
                "MODE 1 of 2 (visual 4): common.turn_off() -- software power off,"
                " BLE stays connected",
                lambda: client.common.turn_off(),
                "the panel should go COMPLETELY DARK. BLE stays up.",
            )
            await step(
                "MODE 2 of 2 (visual 5): common.turn_on()",
                lambda: client.common.turn_on(),
                "the panel comes back. Per P11 the BLUE frame will NOT return -- native"
                " modes survive a power cycle, a DIY frame does not -- so expect the clock"
                " or the last native mode.",
            )
            # KNOWN ANSWER: GREEN (2026-07-26), corroborated by P11. This pair is
            # the apparatus check, not a new question.
            await reclaim_pair("POWER OFF/ON")

        # ------------------------------------------------------------- wrap-up
        print("\n" + "=" * 78, flush=True)
        print(f"SEQUENCE {sequence} ({SEQUENCE_TITLES[sequence]}) -- report:", flush=True)
        print("  1. Did the panel turn RED at attempt A?   (RED => no re-entry needed)", flush=True)
        print("  2. Did the panel turn GREEN at attempt B? (only GREEN => re-entry REQUIRED)", flush=True)
        if sequence == 2:
            print("  3. Did the white diagonal + corner hook appear over the running clock?", flush=True)
            print("     Its own result: the daemon's delta-path assumption stands or falls.", flush=True)
        if sequence == 5:
            print("  NOTE: the expected answer is GREEN. RED here means the probe changed,", flush=True)
            print("        not the device -- do not record a new finding.", flush=True)
        print(f"\nfull ack log: {len(acks)} notification(s) this run (never cleared).", flush=True)

        # Cleanup: leave nothing armed, nothing dark.
        unsubscribe()
        try:
            if sequence == 4:
                await client.countdown.stop()
                await client.chronograph.reset()
            await client.common.turn_on()
        except Exception as ex:
            print(f"cleanup FAILED: {ex!r}", flush=True)
        await client.clock.show()
        print("clock restored. done.", flush=True)


SEQUENCE = select_sequence(sys.argv[1:])
print_visual_script(SEQUENCE)
asyncio.run(main(SEQUENCE))
