"""P4 -- streaming endurance: the SAFE sustained envelope, measured by the probe itself.

WHY THIS PROBE EXISTS
---------------------
probes/probe_streaming_benchmark.py (2026-07-20) already settled the ceiling
questions and this probe does NOT re-measure them:

    acked full frames                1.25-1.35 fps (the with-response round trip
                                     IS the bottleneck, not the ack wait)
    unacked full frames              ~167 fps ingested by the stack
    what the PANEL renders           a hard ~1.75 fps cap -- it samples the
                                     latest frame and drops the rest
    sustained flooding               killed the link TWICE

So the rate question is answered. The question left open is the one GlanceOS
actually needs: what can be sustained for MINUTES without losing the link? A
benchmark that runs for four seconds per phase cannot answer that, and the two
link deaths it caused are the reason to ask.

    1. FRAMES  Unacked full frames paced at exactly 1.5 fps for 10 minutes.
               Below the render cap on purpose -- this is not a rate hunt, it is
               an endurance test of the rate we intend to ship. Alive at the end?
               Throughput flat across all ten minutes? fa03 notifies still ~1:1
               with frames sent, or do they thin out as the device tires?
    2. DELTAS  The graffiti delta ceiling. 255-pixel unacked commands at
               10 / 20 / 40 / 60 cmd/s, 30 s per step, STOPPING at the first sign
               of degradation instead of pushing into another link death. The
               last step that survives IS the animation budget for delta-driven
               scenes.
    3. MIX     The GlanceOS shape: 1 full frame + 10 delta commands per second,
               5 minutes. Keyframe plus animation, the way a real scene renders.

THIS PROBE MEASURES ITSELF -- THERE IS NOTHING TO WATCH
-------------------------------------------------------
Every other probe in this lab asks an operator to read the panel. This one asks
nothing. Frames sent, commands sent, acks received, ack:send ratio, achieved
rate against target, missed pacing slots, reconnects, every write exception, and
time-to-first-degradation are all captured in code and printed as one summary
table when the run ends. The panel shows a sweeping bar and a drifting speckle
band; NONE of it is a measurement, and no one has to be in the room. Start the
phase, leave, read the table.

The table prints even if the run dies mid-phase: it is emitted from a `finally`
around asyncio.run, so a link death that takes the process down with it still
leaves the numbers on screen.

DEGRADATION, DEFINED
--------------------
"Degraded" is not a judgement call here. Four criteria, checked in code; the
FIRST one to trip ends the step immediately and ABANDONS the rest of the phase
(no escalation to a higher rate), and which one tripped is recorded with the
seconds since the step began:

    WRITE_FAILED   a write raised. The exception's repr is recorded verbatim.
                   The transport self-heals inside write() (one retry, and a
                   reconnect on a not-ready client), so reaching this means the
                   healing failed too.
    LINK_DOWN      transport reconnect_count increased, a RECONNECT_STARTED
                   event fired, or is_connected went False. A reconnect that
                   SUCCEEDS still counts: a stream that has to be rebuilt is not
                   a stream that survived.
    ACK_COLLAPSE   acks/frames-sent since the step began fell below 0.50 -- the
                   device has stopped keeping up with what it is being handed.
                   Checked only for steps that send FULL FRAMES. Graffiti is
                   ack-silent by design (type byte 5; the transport refuses to
                   await it at all), so zero acks in a delta step is CORRECT
                   BEHAVIOUR and must never be read as degradation.
    RATE_COLLAPSE  the achieved send rate since the step began fell below 0.75
                   of target -- back-pressure: writes are blocking longer than
                   the pacing interval allows.

Neither ratio criterion is judged during the first 10 s of a step (GRACE_
SECONDS): acks lag their sends by up to ~4.3 s on this panel (P14), and judging
a ratio before the first replies land is the exact instrumentation bug that
manufactured false zero-ack findings here twice.

ACK DISCIPLINE
--------------
The ack list is NEVER cleared. Each step records its start index and reports
only the slice from that index, so a late reply lands in a later step's slice
rather than being destroyed. The number that goes in the table is read only
after SETTLE_SECONDS (2.5 s) of quiet following the step's last send -- the
in-loop reads that drive ACK_COLLAPSE are deliberately lenient (a 0.50 floor
after a 10 s grace) precisely because they read early. Every phase also opens
with ONE ACKED warm-up frame whose full send->ack delta is printed, so the ack
path is proven live before a single unacked byte goes out.

SAFETY
------
This probe deliberately stresses the link; the benchmark that came before it
killed the link twice, and that is expected here.

  * NEVER more than 255 coordinates per graffiti command. 256 in one command
    crashed this panel's BLE stack on 2026-07-25 (P13 phase E): it stopped
    advertising, reconnect raised BleakDeviceNotFoundError, and a PHYSICAL power
    cycle was needed. There is no nack to catch. This probe therefore sends
    exactly DELTA_PIXELS (255) coordinates through display.set_pixels, the
    public batching API -- one command per call, no hand-built graffiti frames,
    and the batching would cap it even if the constant were raised.
  * Every step is wrapped: a failure is recorded and the phase exits cleanly
    rather than crashing mid-stream.
  * Cleanup restores the panel to an ordinary clock face on EVERY exit path,
    including an exception or KeyboardInterrupt.
  * No set_password / verify_password, no ae00 / ae01 UART writes, no
    experimental.delete_device_data, no RTC write, no settings write.

Deltas go through client.display.set_pixels rather than client.graffiti.
set_pixels because that is the call GlanceOS's frame pipeline actually makes
(move_type off); measuring anything else would measure a path nobody ships.

USAGE
-----
    python probes/probe_p4_streaming_endurance.py frames   # ~10.5 min, unattended
    python probes/probe_p4_streaming_endurance.py deltas   # ~2.5 min max, unattended
    python probes/probe_p4_streaming_endurance.py mix      # ~5.5 min, unattended
    python probes/probe_p4_streaming_endurance.py smoke    # ~1 min, harness shakedown

The argument is mandatory and selects exactly ONE phase; a bare invocation
prints this list and exits 2, before any BLE contact. Run `smoke` first if the
probe has been edited -- it exercises all three shapes for 15 s each, so a
broken harness costs a minute instead of ten. `smoke` answers nothing about
endurance and its table must not be recorded as a P4 result.

RESULT (2026-07-28): all three phases ran on the reference 32x32 panel.

    step                          ran  frames  deltas   acks  ack:F  sent/s  target  miss
    full frames 1.5 fps        600.0s     900       0    900   1.00    1.50    1.50     0
    deltas 10 cmd/s             30.0s       0     300      0      -   10.00   10.00     0
    deltas 20 cmd/s             30.0s       0     600      0      -   19.99   20.00     0
    deltas 40 cmd/s             30.0s       0    1200      0      -   39.98   40.00     0
    deltas 60 cmd/s             30.0s       0    1657      0      -   55.23   60.00   143
    mix 1 fps + 10 cmd/s       300.0s     300    2999    218   0.73   11.00   11.00     1

Zero reconnects anywhere. The three sub-items P4 was written to answer are all
answered:

  1. 1.5 FPS FULL FRAMES ARE COMFORTABLY SUSTAINABLE. Ten minutes, 900 frames,
     900 acks -- perfect 1:1 frame-to-ack correspondence, exact pacing, no
     back-pressure, no thinning of the notifies as the device ran on. The safe
     sustained envelope sits just under the known ~1.75 fps device render cap.
  2. THE GRAFFITI DELTA CEILING IS ~40 cmd/s CLEAN. 10, 20 and 40 cmd/s each ran
     exact with zero missed pacing slots. 60 cmd/s could only achieve 55.23/s and
     dropped 143 slots. That is consistent with the previously measured ~20 ms
     per graffiti command (~50/s theoretical). Ship 40 cmd/s; ~55/s is the
     observed hard ceiling, reachable only under back-pressure.
  3. *** INTERLEAVING DELTAS WITH FULL FRAMES COSTS ~27% OF THE FRAME ACKS. ***
     Frames alone: ack:F 1.00. Mixed: ack:F 0.73 over five minutes -- 218 acks
     for 300 frames -- corroborated by the smoke run's 0.87 over 15 s. The fa03
     ack is the device's "frame processed" signal and the SDK's free flow
     control, so mixed-mode streaming degrades flow control by roughly a quarter.
     Anyone designing a delta stream with periodic keyframes must know that
     pacing on frame acks yields materially fewer of them in mixed mode than in
     pure full-frame mode. THE MECHANISM IS UNKNOWN and is not guessed at here.

KNOWN LIMITATIONS OF THIS PROBE -- do not over-trust the summary line
---------------------------------------------------------------------
This run printed "NO DEGRADATION" and "no write failures" on all three phases.
Both statements are narrower than they read:

  * CLEANUP IS NOT INSTRUMENTED. The `deltas` and `mix` phases each ended with
    the cleanup clock write failing `Unreachable`, forcing a transport
    reconnect. None of that reaches the summary table, which stops measuring
    when the last step ends. Post-phase damage is invisible here by
    construction. Those cleanup failures remain UNEXPLAINED: probe_p4b_post_
    stream_write.py tested the obvious hypothesis (that graffiti streaming
    breaks the next write) and did NOT reproduce it, so nothing about them is
    recorded as a defect -- see that probe's RESULT for what was ruled out.
  * ACK_COLLAPSE'S FLOOR IS 0.50. The `mix` phase's 0.73 is a real and important
    degradation of flow control, and the criterion never fired. A ratio this
    probe calls healthy can still be a quarter down on pure full-frame mode.
  * MISSED SLOTS ARE NOT A DEGRADATION CRITERION. The 60 cmd/s step's 143
    missed slots are unambiguous back-pressure, but 55.23/60 = 0.92 sits well
    above the 0.75 RATE_COLLAPSE trigger, so the step was scored clean.

Read the `miss` column and the phase's exit behaviour, not just the verdict line.
"""

import asyncio
import sys
import time
from dataclasses import dataclass, field

from pyidotmatrix import IDotMatrixClient, ScreenSize, TransportEvent, TransportEventKind

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

DELTA_PIXELS = 255  # HARD CEILING per graffiti command -- see SAFETY above
MIX_DELTA_HZ = 10.0  # the "N" in "1 full frame + N deltas per second"

SETTLE_SECONDS = 2.5  # quiet after the last send, BEFORE the ack slice is read
GRACE_SECONDS = 10.0  # no ratio judgement before this much of a step has run
CHECK_EVERY = 5.0  # how often the degradation criteria are evaluated
PROGRESS_EVERY = 30.0  # heartbeat line, so an unattended run is not silent
ACK_RATIO_FLOOR = 0.50  # acks per full frame sent, below which = ACK_COLLAPSE
RATE_FLOOR = 0.75  # fraction of target send rate, below which = RATE_COLLAPSE


@dataclass(frozen=True)
class Step:
    """One paced segment: full frames and/or delta commands, both per second."""

    label: str
    seconds: float
    frames_hz: float
    deltas_hz: float

    @property
    def judges_acks(self) -> bool:
        """Only full frames ack. A silent delta step is correct, not degraded."""
        return self.frames_hz > 0.0

    @property
    def target_hz(self) -> float:
        return self.frames_hz + self.deltas_hz


PHASES: dict[str, tuple[str, tuple[Step, ...]]] = {
    "frames": (
        "unacked full frames at exactly 1.5 fps for 10 minutes (~10.5 min)",
        (Step("full frames 1.5 fps", 600.0, 1.5, 0.0),),
    ),
    "deltas": (
        "graffiti delta ceiling: 255-px commands at 10/20/40/60 cmd/s, 30 s each (~2.5 min max)",
        (
            Step("deltas 10 cmd/s", 30.0, 0.0, 10.0),
            Step("deltas 20 cmd/s", 30.0, 0.0, 20.0),
            Step("deltas 40 cmd/s", 30.0, 0.0, 40.0),
            Step("deltas 60 cmd/s", 30.0, 0.0, 60.0),
        ),
    ),
    "mix": (
        f"the GlanceOS mix: 1 full frame + {MIX_DELTA_HZ:.0f} deltas per second, 5 minutes (~5.5 min)",
        (Step(f"mix 1 fps + {MIX_DELTA_HZ:.0f} cmd/s", 300.0, 1.0, MIX_DELTA_HZ),),
    ),
    "smoke": (
        "harness shakedown: 15 s of each shape (~1 min). NOT an endurance result",
        (
            Step("smoke frames 1.5 fps", 15.0, 1.5, 0.0),
            Step("smoke deltas 10 cmd/s", 15.0, 0.0, 10.0),
            Step("smoke mix 1 fps + 10 cmd/s", 15.0, 1.0, 10.0),
        ),
    ),
}


@dataclass
class StepResult:
    """Everything the summary table prints for one step."""

    label: str
    target_hz: float
    planned_seconds: float
    ran_seconds: float = 0.0
    frames_sent: int = 0
    deltas_sent: int = 0
    missed_slots: int = 0  # pacing slots skipped because a send ran long
    acks: int = 0  # settled count, read after SETTLE_SECONDS
    first_ack_delta: float | None = None  # send->ack, first reply of the step
    reconnects: int = 0
    degradation: str | None = None
    degraded_at: float | None = None  # seconds into the step
    failures: list[str] = field(default_factory=list)  # verbatim exception reprs

    @property
    def sent(self) -> int:
        return self.frames_sent + self.deltas_sent

    @property
    def achieved_hz(self) -> float:
        return self.sent / self.ran_seconds if self.ran_seconds > 0 else 0.0

    @property
    def ack_ratio(self) -> float | None:
        """Acks per FULL FRAME. None for delta-only steps, which never ack."""
        return self.acks / self.frames_sent if self.frames_sent else None


def print_usage() -> None:
    print("usage: python probes/probe_p4_streaming_endurance.py <phase>", flush=True)
    print("", flush=True)
    print("Runs exactly ONE phase. The argument is mandatory.", flush=True)
    for key, (description, _) in PHASES.items():
        print(f"    {key:8s} {description}", flush=True)


def select_phase(argv: list[str]) -> str:
    """Validated before any BLE contact, so a typo cannot start a 10-minute run."""
    if not argv:
        print("error: a phase name is required.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    if len(argv) > 1:
        print(f"error: expected exactly one phase name, got {len(argv)}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    if argv[0] not in PHASES:
        print(f"error: unrecognized phase {argv[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    return argv[0]


def print_run_script(phase: str) -> None:
    """Everything that will happen, printed before connecting."""
    description, steps = PHASES[phase]
    total = sum(step.seconds for step in steps) + SETTLE_SECONDS * len(steps) + 20.0
    print("", flush=True)
    print("=== WHAT THIS RUN DOES ======================================================", flush=True)
    print(f"  phase {phase}: {description}", flush=True)
    print("  steps, in order (each ends early if it degrades -- see below):", flush=True)
    for index, step in enumerate(steps, start=1):
        parts = []
        if step.frames_hz:
            parts.append(f"{step.frames_hz:g} full frame/s (unacked)")
        if step.deltas_hz:
            parts.append(f"{step.deltas_hz:g} x {DELTA_PIXELS}-px graffiti command/s (unacked)")
        print(f"    {index}. {step.label:26s} {step.seconds:5.0f}s   " + " + ".join(parts), flush=True)
    print(f"  worst-case wall clock including settles and cleanup: ~{total / 60:.1f} min", flush=True)
    print("", flush=True)
    print("  THERE IS NOTHING TO WATCH. The panel will show a sweeping coloured bar and a", flush=True)
    print("  drifting speckle band; neither is a measurement and neither needs judging.", flush=True)
    print("  Every number this probe reports is captured in code and printed as one", flush=True)
    print("  summary table at the end -- including if the run dies. You can leave.", flush=True)
    print("", flush=True)
    print("  The link may well die: the 2026-07-20 flood benchmark killed it twice. That", flush=True)
    print("  is a recorded outcome here, not a failed run. A step STOPS at the first", flush=True)
    print(f"  degradation (a write raising, a reconnect, ack ratio under {ACK_RATIO_FLOOR:.2f}, or", flush=True)
    print(f"  achieved rate under {RATE_FLOOR:.2f} of target) and the phase does NOT escalate further.", flush=True)
    print("  Cleanup puts the panel back on the ordinary clock face on every exit path.", flush=True)
    print("=============================================================================", flush=True)


# --- test content: cheap to produce, obviously moving, never a measurement ----

_WIDTH = SCREEN.width
_HEIGHT = SCREEN.height
_FRAME_BYTES = _WIDTH * _HEIGHT * 3
_ALL_COORDS = [(x, y) for y in range(_HEIGHT) for x in range(_WIDTH)]
_PALETTE = ((255, 40, 40), (40, 255, 80), (60, 120, 255), (255, 220, 0), (255, 0, 255), (0, 255, 255))


def _build_frames() -> list[bytes]:
    """One frame per bar position, precomputed so pacing never waits on the CPU."""
    frames = []
    for position in range(_WIDTH):
        rgb = bytearray(_FRAME_BYTES)
        color = _PALETTE[position % len(_PALETTE)]
        for y in range(_HEIGHT):
            for dx in range(3):
                offset = (y * _WIDTH + (position + dx) % _WIDTH) * 3
                rgb[offset : offset + 3] = bytes(color)
        frames.append(bytes(rgb))
    return frames


_FRAMES = _build_frames()


def delta_coords(index: int) -> list[tuple[int, int]]:
    """Exactly DELTA_PIXELS coordinates, drifting by a stride coprime with 1024.

    One call = one graffiti command: display.set_pixels batches at
    graffiti.MAX_PIXELS_PER_COMMAND (255), and DELTA_PIXELS IS 255, so this
    never splits and never exceeds the hard limit.
    """
    start = (index * 137) % len(_ALL_COORDS)
    window = _ALL_COORDS[start : start + DELTA_PIXELS]
    if len(window) < DELTA_PIXELS:
        window = window + _ALL_COORDS[: DELTA_PIXELS - len(window)]
    return window


# --- the run -----------------------------------------------------------------


async def run_step(
    client: IDotMatrixClient,
    step: Step,
    acks: list[tuple[float, str]],
    events: list[TransportEvent],
) -> StepResult:
    """Paces one step to its wall clock, stopping at the first degradation."""
    result = StepResult(step.label, step.target_hz, step.seconds)
    mark = len(acks)
    reconnects_before = client.snapshot().reconnect_count
    events_before = len(events)

    frame_interval = 1.0 / step.frames_hz if step.frames_hz else float("inf")
    delta_interval = 1.0 / step.deltas_hz if step.deltas_hz else float("inf")
    started = time.perf_counter()
    end_at = started + step.seconds
    next_frame_at = started if step.frames_hz else float("inf")
    next_delta_at = started if step.deltas_hz else float("inf")
    next_check_at = started + GRACE_SECONDS
    next_progress_at = started + PROGRESS_EVERY

    def trip(criterion: str, at: float, detail: str = "") -> None:
        result.degradation = criterion
        result.degraded_at = at - started
        print(
            f"    *** {criterion} at {result.degraded_at:.1f}s into the step"
            f"{' -- ' + detail if detail else ''} -- stopping, no escalation ***",
            flush=True,
        )

    while True:
        now = time.perf_counter()
        if now >= end_at:
            break
        due = min(next_frame_at, next_delta_at, next_check_at, next_progress_at, end_at)
        if due > now:
            await asyncio.sleep(due - now)
        now = time.perf_counter()
        if now >= end_at:
            break

        if now >= next_frame_at:
            try:
                await client.display.show_frame(_FRAMES[result.frames_sent % _WIDTH], wait_for_device=False)
                result.frames_sent += 1
            except Exception as ex:
                result.failures.append(f"show_frame: {ex!r}")
                trip("WRITE_FAILED", time.perf_counter(), repr(ex))
                break
            now = time.perf_counter()
            while next_frame_at <= now:
                next_frame_at += frame_interval
                result.missed_slots += 1
            result.missed_slots -= 1  # the slot just served is not a miss

        if now >= next_delta_at:
            index = result.deltas_sent
            try:
                await client.display.set_pixels(
                    _PALETTE[index % len(_PALETTE)], delta_coords(index), wait_for_device=False
                )
                result.deltas_sent += 1
            except Exception as ex:
                result.failures.append(f"set_pixels: {ex!r}")
                trip("WRITE_FAILED", time.perf_counter(), repr(ex))
                break
            now = time.perf_counter()
            while next_delta_at <= now:
                next_delta_at += delta_interval
                result.missed_slots += 1
            result.missed_slots -= 1

        now = time.perf_counter()
        elapsed = now - started

        # LINK_DOWN is checked every pass, not on the CHECK_EVERY cadence: a
        # reconnect is unambiguous and there is no reason to keep streaming
        # into a link that has already been rebuilt underneath us.
        reconnects = client.snapshot().reconnect_count - reconnects_before
        new_events = [e for e in events[events_before:] if e.kind is not TransportEventKind.WRITE_FAILED]
        if reconnects or new_events or not client.is_connected:
            result.reconnects = reconnects
            detail = f"reconnects={reconnects} connected={client.is_connected}"
            if new_events:
                detail += f" events={[e.kind.value for e in new_events]}"
            trip("LINK_DOWN", now, detail)
            break

        if now >= next_check_at:
            next_check_at = now + CHECK_EVERY
            achieved = result.sent / elapsed if elapsed > 0 else 0.0
            if step.target_hz and achieved < RATE_FLOOR * step.target_hz:
                trip("RATE_COLLAPSE", now, f"{achieved:.2f} of {step.target_hz:.2f} cmd/s targeted")
                break
            if step.judges_acks and result.frames_sent:
                # Read early ON PURPOSE (lenient floor, post-grace); the number
                # that goes in the table is the settled one, read below.
                ratio = (len(acks) - mark) / result.frames_sent
                if ratio < ACK_RATIO_FLOOR:
                    trip("ACK_COLLAPSE", now, f"{len(acks) - mark} acks for {result.frames_sent} frames = {ratio:.2f}")
                    break

        if now >= next_progress_at:
            next_progress_at = now + PROGRESS_EVERY
            print(
                f"    {elapsed:6.0f}s  frames {result.frames_sent:5d}  deltas {result.deltas_sent:6d}"
                f"  acks {len(acks) - mark:5d}  {result.sent / elapsed:6.2f}/s"
                f"  connected={client.is_connected}",
                flush=True,
            )

    result.ran_seconds = time.perf_counter() - started
    result.reconnects = client.snapshot().reconnect_count - reconnects_before

    # SETTLE BEFORE READING. The list is never cleared; this step reports only
    # the slice since its own mark, so a reply later than the settle lands in a
    # later step's slice instead of being destroyed.
    await asyncio.sleep(SETTLE_SECONDS)
    window = acks[mark:]
    result.acks = len(window)
    if window:
        result.first_ack_delta = window[0][0] - started
    for event in events[events_before:]:
        if event.kind is TransportEventKind.WRITE_FAILED:
            result.failures.append(f"transport WRITE_FAILED: {event.detail}")
    return result


async def warm_up(client: IDotMatrixClient, acks: list[tuple[float, str]]) -> None:
    """ONE acked full frame, its send->ack delta printed.

    Proves the ack path is live before any unacked byte goes out -- otherwise a
    phase reporting zero acks cannot distinguish a tired device from a probe
    that was never listening. Also enters DIY mode, so the paced loop's first
    send is a plain frame write and not a mode entry.
    """
    print("\n  warm-up: one ACKED full frame (also enters DIY mode)", flush=True)
    mark = len(acks)
    sent_at = time.perf_counter()
    await client.display.show_frame(_FRAMES[0], wait_for_device=True)
    await asyncio.sleep(SETTLE_SECONDS)
    window = acks[mark:]
    if window:
        for at, text in window:
            print(f"    ack {at - sent_at:+.2f}s after send  {text}", flush=True)
    else:
        print(
            f"    *** ZERO ACKS after {SETTLE_SECONDS:.1f}s *** -- genuine silence; the list "
            "was not read early and is never cleared. Treat this run's ack column with "
            "suspicion.",
            flush=True,
        )


async def main(phase: str, results: list[StepResult]) -> None:
    description, steps = PHASES[phase]
    print(f"phase: {phase} -- {description}", flush=True)
    print_run_script(phase)
    print("\nconnecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, SCREEN) as client:
        acks: list[tuple[float, str]] = []  # NEVER cleared
        events: list[TransportEvent] = []
        unsubscribe_acks = client.add_response_listener(lambda ack: acks.append((time.perf_counter(), repr(ack))))
        unsubscribe_events = client.add_event_listener(events.append)
        try:
            await warm_up(client, acks)
            for step in steps:
                print(f"\n--- {step.label} ({step.seconds:.0f}s, target {step.target_hz:g}/s) ---", flush=True)
                try:
                    result = await run_step(client, step, acks, events)
                except Exception as ex:
                    # A step must never take the phase down uncleaned.
                    result = StepResult(step.label, step.target_hz, step.seconds)
                    result.degradation = "WRITE_FAILED"
                    result.failures.append(f"step aborted: {ex!r}")
                    print(f"    step aborted: {ex!r}", flush=True)
                results.append(result)
                if result.degradation:
                    print("    phase stops here -- the remaining steps are NOT run.", flush=True)
                    break
        finally:
            print("\n--- cleanup ---", flush=True)
            try:
                await client.clock.show()
                print("panel restored to the clock face.", flush=True)
            except Exception as ex:
                print(
                    f"*** CLOCK RESTORE FAILED: {ex!r} -- the panel is still showing test "
                    "content. Reconnect and run any clock probe, or power-cycle. ***",
                    flush=True,
                )
            unsubscribe_acks()
            unsubscribe_events()
    print("disconnected.", flush=True)


def print_summary(phase: str | None, results: list[StepResult]) -> None:
    """The whole run on one screen -- printed even if the run died."""
    print("\n=== P4 SUMMARY ==============================================================", flush=True)
    if phase is None or not results:
        print("  no step completed -- nothing to report.", flush=True)
        print("=============================================================================", flush=True)
        return
    print(f"  phase: {phase}", flush=True)
    header = (
        f"  {'step':26s} {'ran':>7s} {'frames':>7s} {'deltas':>7s} {'acks':>6s} "
        f"{'ack:F':>6s} {'sent/s':>7s} {'target':>7s} {'miss':>5s} {'rc':>3s}  degradation"
    )
    print(header, flush=True)
    for result in results:
        ratio = result.ack_ratio
        degraded = "-"
        if result.degradation:
            at = f"{result.degraded_at:.1f}s" if result.degraded_at is not None else "?"
            degraded = f"{result.degradation} @ {at}"
        print(
            f"  {result.label:26s} {result.ran_seconds:6.1f}s {result.frames_sent:7d} "
            f"{result.deltas_sent:7d} {result.acks:6d} "
            f"{('-' if ratio is None else f'{ratio:.2f}'):>6s} {result.achieved_hz:7.2f} "
            f"{result.target_hz:7.2f} {result.missed_slots:5d} {result.reconnects:3d}  {degraded}",
            flush=True,
        )
    print("  ack:F = acks per FULL FRAME sent. '-' = a delta-only step: graffiti is", flush=True)
    print("  ack-silent by design, so zero acks there is correct, not degradation.", flush=True)
    print("  miss = pacing slots skipped because a send overran its interval.", flush=True)
    print("  rc = reconnects during the step.", flush=True)

    failures = [(result.label, text) for result in results for text in result.failures]
    if failures:
        print("\n  WRITE FAILURES (verbatim):", flush=True)
        for label, text in failures:
            print(f"    {label}: {text}", flush=True)
    else:
        print("\n  no write failures.", flush=True)

    degraded = [result for result in results if result.degradation]
    survived = [result for result in results if not result.degradation]
    if not degraded:
        print("\n  => NO DEGRADATION. Every step ran its full duration with the link intact.", flush=True)
        if survived:
            best = max(survived, key=lambda r: r.target_hz)
            print(
                f"     Highest rate sustained: {best.target_hz:g}/s for {best.ran_seconds:.0f}s ({best.label}).",
                flush=True,
            )
    else:
        first = degraded[0]
        print(
            f"\n  => DEGRADED at '{first.label}' ({first.degradation}, "
            f"{first.degraded_at:.1f}s in). Nothing above that rate was attempted.",
            flush=True,
        )
        if survived:
            best = max(survived, key=lambda r: r.target_hz)
            print(
                f"     Last clean step: {best.label} -- {best.target_hz:g}/s held for "
                f"{best.ran_seconds:.0f}s. THAT is the budget, not the step that broke.",
                flush=True,
            )
        else:
            print(
                "     No step survived. Do not derive a budget from this run; re-run "
                "`smoke` first to rule out the harness.",
                flush=True,
            )
    print("  One run is one data point. Repeat before writing a number into capabilities.py.", flush=True)
    print("=============================================================================", flush=True)


_PHASE = select_phase(sys.argv[1:])
_RESULTS: list[StepResult] = []
try:
    asyncio.run(main(_PHASE, _RESULTS))
finally:
    # Emitted from here so a link death that kills the run still leaves the
    # numbers on screen -- an unattended probe whose table is lost measured
    # nothing.
    print_summary(_PHASE, _RESULTS)
