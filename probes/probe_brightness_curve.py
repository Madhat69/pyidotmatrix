"""Brightness response curve, measured TWICE at two sensor distances.

WHY THIS EXISTS
---------------
Tonight (2026-07-27) the panel was metered with a phone lux sensor about two
inches away, in a light-tight chamber, on a full-white field held 25 s per step
(probes/probe_p17b_eco_isolation.py, phases 1-4):

    brightness    5  ->    4.69 lux
    brightness   40  ->   62.28 lux
    brightness  100  ->   65.84 lux

A drift check -- 100% measured twice, 26 minutes apart -- agreed to one part in
6000, so the readings themselves are sound. But 40% delivering 95% of the light
of 100% is an extraordinary claim, and there are exactly two ordinary
explanations:

  (a) THE PANEL'S RESPONSE IS GENUINELY COMPRESSED. Then most of the SDK's 5-100
      range does almost nothing, every perceptible step of dimming lives below
      roughly 20, and a linear 0-100 slider is the wrong control to expose. That
      would reshape any night-mode feature and directly implicates eco_brightness
      (whose own A/B is being read against this same ladder).
  (b) THE SENSOR COMPRESSED, not the panel. Phone ambient-light sensors are built
      for room lighting; two inches from a lit panel puts them near the top of
      their range, where they flatten. The panel would then be perfectly linear
      and the finding an artifact of the measurement.

Three points cannot separate these. Eleven points measured once still cannot:
a compressed curve and a compressed sensor produce the SAME single curve.

THE DISCRIMINATOR IS DISTANCE, NOT CALIBRATION
-----------------------------------------------
No absolute calibration is needed, and none is available. Illuminance falls off
as 1/r^2, so moving the sensor scales EVERY reading in a run by the same
constant -- which means RATIOS WITHIN A RUN ARE DISTANCE-INVARIANT. The ratio
lux(40) / lux(100) is a property of the panel alone, if the sensor is behaving.

So: run the identical ladder at two distances and compare the ratio, not the
values.

  * ratio stays ~0.95 at both distances => the compression is IN THE PANEL. It
    survived a change that scaled the raw numbers by a large factor, which no
    sensor artifact does. The curve is real; act on it.
  * ratio falls toward ~0.4 at the farther distance => the near run was SENSOR
    COMPRESSION. The far run is the true curve, because backing the sensor off
    moves it out of saturation and into its linear region. Discard the near
    readings and re-derive the curve from the far ones.
  * ratios differ but neither is near 0.4 => partial saturation; the far run is
    still the better estimate, and the honest conclusion is "the curve is
    compressed, by an amount this rig cannot pin down". Say that rather than
    quoting a number.

The far run must be FARTHER, not nearer: the failure mode being tested for is
saturation, and only backing off can relieve it. Doubling the distance is a good
choice -- it drops every reading ~4x, which is a big enough change that a sensor
artifact cannot survive it, while keeping the dim end of the ladder above the
noise floor.

DESIGN
------
An 11-rung ladder -- 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100 -- on a
FULL-WHITE color.show field, the maximum lit area the panel can produce and the
same target the original three points used. The low end is deliberately denser
(5, 10, 20 before the regular 10s) because that is where hypothesis (a) predicts
all the real dynamic range lives; a uniform 10-step ladder would spend most of
its rungs where nothing happens.

Each rung: a ~3 s scoreboard label, then the white field held 15 s with NOTHING
SENT during the hold. The operator uses a LOGGING meter, so what matters is that
each hold is a flat plateau with a clean edge on either side -- the log can then
be segmented by eye afterwards. The ack report for a rung is printed BEFORE its
hold starts, so the settle wait never eats into a plateau.

Scoreboard labels read `brightness | run`: count1 is the BRIGHTNESS VALUE, count2
is 1 or 2 for the run. The two number sets are disjoint on purpose -- no ladder
rung is 1 or 2 -- so the label stays unambiguous even if count1/count2 render in
the opposite orientation to what we expect.

Run A, then an INTERMISSION for repositioning, then Run B: the identical ladder,
in the identical order, with ONLY the sensor moved. Nothing else may change --
not the room, not the chamber, not the panel's position. The ratio argument
above depends on the two runs differing in exactly one variable.

THE INTERMISSION IS AUDIBLE, BECAUSE THE OPERATOR IS NOT WATCHING
------------------------------------------------------------------
During the intermission the operator has their hands on the phone inside a
light-tight chamber and cannot see the panel or the terminal. Visual cues are
useless there, so the intermission is bracketed by two BUZZES:

    BUZZ 1 (10 s)  =  "start moving the sensor now"
    a 1-minute countdown shown on the panel, for anyone who glances over
    BUZZ 2 (10 s)  =  "run B is resuming -- hands off"

BUZZER MECHANISM: there is no standalone beep command in this driver. The only
buzzer the device exposes is the ALARM buzzer, so each buzz is a real Timer slot
armed through client.experimental.timer_set with buzzer_enable=True and
duration_bucket=DURATION_10S (bucket 0 = 10 s, the shortest the firmware
offers), then fired deterministically by RTC SPOOFING -- the same technique that
mapped the Timer week bits (probes/probe_timer_weekbit.py, 2026-07-21), where
set_time was proved to drive the RTC the alarm schedule is evaluated against.

Order matters: the slot is UPLOADED FIRST and the RTC is jumped afterwards, to
12:00:50 with the slot armed for 12:01. The fire is then a fixed 10 s away and
the multi-second BLE upload cannot eat into that margin -- spoofing first and
racing the upload would make the interval depend on link speed. The week mask is
all seven days (build_timer_week(range(7))), so the calendar date is irrelevant
and nothing here depends on the day-bit map.

capabilities.py records the fire signature as BUZZER FIRST, content ~1-2 s
later, so the audible edge leads and is what the operator keys on; the amber
content that follows is incidental. Each slot is CLOSED after its fire, and the
true RTC is restored the moment the intermission ends -- the clock is spoofed for
under two minutes of a ten-minute run, and never while a measurement is taken.

The countdown is stopped before BUZZ 2 rather than left running: capabilities.py
notes that the native timer modes share device-side state (a paused countdown
was seen hijacking chronograph commands, 2026-07-20), and an alarm firing over a
live countdown is exactly the sort of overlap that has bitten us before. It
costs nothing -- buzz 2 is itself the end-of-intermission signal.

ACK DISCIPLINE
--------------
On 2026-07-25 two probes printed their ack reports in the same breath as the
send and then cleared the ack list at the phase boundary. Replies land 0.3-4.3 s
later, into an already-emptied list, so those runs reported ack SILENCE that was
purely their own impatience -- one hardware run wasted and a retraction filed.
Here: AckLog never clears (it tracks a read cursor, so a late ack surfaces in
the NEXT report instead of vanishing), every report sleeps ACK_SETTLE before
reading, and each ack prints its delta from the send it is attributed to.

SAFETY / RESTORATION
--------------------
No set_password / verify_password, no writes to the ae00/ae01 UART service, no
delete_device_data. common.reset() (04 00 03 80) is verified non-destructive
(used live 2026-07-18 to clear a stuck state) and is the only reset here.

Cleanup is a `finally` and runs on every exit path -- exception, phase failure,
KeyboardInterrupt -- in this order:

    1. THE TRUE RTC, first, before anything that could fail. A panel left on a
       spoofed date fires alarms at wrong wall-clock times and corrupts every
       later observation.
    2. Every slot this probe armed, CLOSED. The buzz alarms are armed for all
       seven days; a stranded one would beep at 12:01 daily, forever.
    3. The countdown, stopped.
    4. Brightness 100 and the clock, so the panel is left usable.

This matters more than usual here because the operator spends the middle of the
run walking away from the panel with their hands in a chamber -- a probe that
dies mid-intermission must not leave a spoofed clock and an armed alarm behind.

READOUT
-------
Compute lux(40)/lux(100) for EACH run and compare the two ratios -- that single
comparison is the whole experiment:

  * both ratios ~0.95  => THE PANEL'S CURVE IS REAL AND COMPRESSED. Everything
    above ~40 is cosmetic. The SDK should document the usable dimming range as
    roughly 5-30, night mode should live there, and eco_brightness values above
    40 should be understood as "no meaningful dimming".
  * near ~0.95, far ~0.4 => THE NEAR RUN WAS SENSOR SATURATION. Tonight's
    three-point finding is VOID. Re-derive the curve from the far run only, and
    treat every past reading taken at two inches as suspect -- including
    P17b's calibration phases, which used that same geometry.
  * ratios differ, neither near 0.4 => partial saturation. Report the far run as
    a lower bound on the compression and do not quote a curve.
  * the far run's dim rungs (5, 10) read at or below the meter's noise floor =>
    the far distance was too far; the ratio at the BRIGHT end still stands, but
    the shape of the low end must come from the near run.

Also worth recording from either run:
  * where the curve FLATTENS (the first rung whose reading is within a few
    percent of 100's) -- that is the practical top of the useful range.
  * whether 5 -> 10 -> 20 are clearly separated. Tonight's 5 read 4.69 lux
    against 40's 62.28, so the low end has real range; if the rungs there are
    NOT separated, the panel has fewer usable levels than the API suggests and
    GlanceOS should quantize its brightness control accordingly.
  * any rung that reads NON-MONOTONICALLY (a higher setting reading dimmer).
    That would mean the brightness byte is not a simple level and is a separate
    finding worth its own probe.

USAGE
-----
    python probes/probe_brightness_curve.py

No arguments. Runtime ~10 minutes: two 11-rung ladders at ~21 s per rung
(3 s label + ~2.5 s ack settle + 15 s hold) = ~3 min 45 s each, plus a ~2 min
intermission and ~20 s of baseline and cleanup. The operator sets the sensor at
position 1, starts the
probe, moves the sensor only between the two buzzes, and does not touch anything
else until the panel returns to the clock.

RESULT (2026-07-27): RAN, ratio confirmed at two distances. lux(40)/lux(100)
agreed between the near (~2in) and far (~4in) runs to within 1-2% at every
rung of the ladder -- a match that sensor saturation cannot survive, since
saturation would have compressed the near run's ratio toward 1.0 relative to
the far run's. THE PANEL'S CURVE IS REAL AND COMPRESSED, not a measurement
artifact: brightness 50-100 are effectively indistinguishable (40% already
delivers within ~6% of 100%'s output), the usable dimming range is roughly
5 to ~42, and the shape is consistent with firmware computing something like
min(255, percent*6). CORRECTION ON RECORD: doubling the sensor distance was
originally expected to drop every reading ~4x under an inverse-square,
point-source model; the measured drop was instead ~0.74x, because the panel
is an extended light source inside a small reflective chamber rather than a
point source in open air. That wrong prediction does not undermine the
conclusion above, which rests on the RATIO staying stable across distance,
not on the absolute drop matching any particular physical model -- but the
0.74x/4x mismatch is recorded so nobody reuses the inverse-square figure as
a calibration constant for this rig. See capabilities.py's common.
set_brightness entry and probes/probe_p17b_eco_isolation.py's SETTLED section
(phases 1-4), which independently corroborate the same compressed curve at
a fixed 2in distance.
"""

import asyncio
import io
import time
from datetime import datetime, timedelta
from datetime import time as clock_time

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import timer

ADDRESS = "6D:FD:F8:A0:3E:AF"

WHITE = (255, 255, 255)  # the measurement target: maximum lit area, always
PINNED = 100  # the level the panel is left at

# Denser at the bottom: hypothesis (a) predicts all the real dynamic range lives
# below ~20, so a uniform 10-step ladder would waste most of its rungs.
LADDER = (5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)

# The ratio the whole experiment turns on. Kept as named constants so the
# runtime prompts and the docstring's argument cannot drift apart.
RATIO_NUMERATOR = 40
RATIO_DENOMINATOR = 100

LABEL_SECONDS = 3  # scoreboard label: short, then get out of the way
HOLD_SECONDS = 15  # every measurement hold: a flat plateau, nothing sent
ACK_SETTLE = 2.5  # never report an ack list sooner than this after a send

# --- intermission buzzer -----------------------------------------------------
# One slot, reused for both buzzes and closed after each. Armed for all seven
# days so the calendar date is irrelevant; see the docstring's BUZZER MECHANISM.
BUZZ_SLOT = 0
BUZZ_FIRE_AT = clock_time(12, 1)  # the armed minute
BUZZ_SPOOF_AT = clock_time(12, 0, 50)  # RTC is jumped here AFTER the upload -> fire in 10 s
BUZZ_LEAD_SECONDS = 10  # spoof -> fire
BUZZ_TAIL_SECONDS = 12  # the 10 s buzz plus the content's 1-2 s ritual
COUNTDOWN_MINUTES = 1


class AckLog:
    """Ack collector that refuses to report before the device could have replied.

    The 2026-07-25 instrumentation bug in full: report immediately after the
    send, read an empty list, then clear that list at the phase boundary before
    the reply ever arrives -- producing a confident "ZERO ACKS" finding that was
    an artifact of the probe. Replies on this panel have been measured anywhere
    from ~0.3 s to ~4.3 s after the write.

    So this class: (a) never clears -- it tracks a read cursor instead, so a
    late ack surfaces in the NEXT report rather than vanishing; (b) sleeps
    ACK_SETTLE inside report() before reading; (c) prints every ack's delta from
    the send it is attributed to, which is the only way to tell a reply to THIS
    command from the tail of the last one.
    """

    def __init__(self) -> None:
        self._entries: list[tuple[float, str]] = []
        self._reported = 0

    def record(self, ack: object) -> None:
        self._entries.append((time.perf_counter(), repr(ack)))

    async def report(self, label: str, sent_at: float) -> None:
        await asyncio.sleep(ACK_SETTLE)
        fresh = self._entries[self._reported :]
        self._reported = len(self._entries)
        if not fresh:
            print(
                f"  ACK {label}: NONE within {ACK_SETTLE:.1f}s of the send -- record it, silence is itself a result",
                flush=True,
            )
            return
        print(f"  ACK {label}: {len(fresh)}", flush=True)
        for at, text in fresh:
            delta = at - sent_at
            note = "  <-- LATE, probably the previous send's reply" if delta > ACK_SETTLE else ""
            print(f"    send+{delta:5.2f}s  {text}{note}", flush=True)


def spoof_datetime(at: clock_time) -> datetime:
    """A naive local datetime on TOMORROW's date at the given wall time.

    Tomorrow, never today: if this probe dies with the clock spoofed, an
    obviously wrong DATE is far easier to notice than a wrong time of day. The
    weekday does not matter -- the buzz alarm is armed for all seven days.

    Naive on purpose: common.build_set_time converts a tz-AWARE datetime with
    .astimezone() and encodes a naive one unchanged as device-local wall time,
    which is exactly what a spoof wants.
    """
    return datetime.combine(datetime.now().date() + timedelta(days=1), at)


def build_buzz_gif(size: int) -> bytes:
    """A 2-frame amber flash: the buzz alarm's content.

    Incidental -- the audible edge is the operator's cue and arrives 1-2 s
    ahead of this -- but timer_set requires a non-empty payload, and amber is
    unmistakably not the white measurement field, so a glance at the panel
    confirms "this is the intermission, not a rung".

    RGB frames left to Pillow's own palettization, the encoding hardware-
    confirmed to render at fire time (probes/probe_timer_image.py, 2026-07-12).
    An older probe hand-built P-mode frames with putpalette() and displayed
    solid black on hardware because palette index 1 fell in the black half; RGB
    frames sidestep that class of bug. optimize=True is required -- without it
    the transfer breaks (see protocol/gif.py).
    """
    frame_a = Image.new("RGB", (size, size), (255, 150, 0))
    frame_b = Image.new("RGB", (size, size), (0, 0, 0))
    buffer = io.BytesIO()
    frame_a.save(
        buffer, format="GIF", save_all=True, optimize=True, append_images=[frame_b], loop=0, duration=250, disposal=2
    )
    return buffer.getvalue()


def make_buzz_alarm() -> timer.Timer:
    """The alarm slot used as a beeper.

    All seven days, so the spoofed date is irrelevant and nothing depends on the
    day-bit map. DURATION_10S is bucket 0 = 10 seconds (protocol/timer.py's
    DURATION_SECONDS), the shortest bucket the firmware offers.
    """
    return timer.Timer(
        num=BUZZ_SLOT,
        week=timer.build_timer_week(range(7)),
        hour=BUZZ_FIRE_AT.hour,
        minute=BUZZ_FIRE_AT.minute,
        duration_bucket=timer.DURATION_10S,
        content_type=timer.CONTENT_GIF,
        buzzer_enable=True,
    )


async def buzz(client: IDotMatrixClient, log: AckLog, payload: bytes, armed: list[timer.Timer], meaning: str) -> None:
    """Ten seconds of alarm buzzer, fired deterministically off a spoofed RTC.

    UPLOAD FIRST, THEN JUMP THE CLOCK. The upload takes multiple seconds on the
    BLE link; spoofing first would let that latency eat an unknown share of the
    lead time and make the buzz land early or not at all. Arming first makes the
    interval a fixed BUZZ_LEAD_SECONDS from a single set_time write.

    The slot is appended to `armed` BEFORE it is uploaded, so cleanup will close
    it even if this call raises partway through.
    """
    alarm = make_buzz_alarm()
    armed.append(alarm)

    print(f"\n--- BUZZ: {meaning} ---", flush=True)
    sent_at = time.perf_counter()
    await client.experimental.timer_set(alarm, payload)
    await log.report("buzz slot upload (expect StatusAck status=3 SAVED)", sent_at)

    sent_at = time.perf_counter()
    await client.device.set_time(spoof_datetime(BUZZ_SPOOF_AT))
    await log.report(f"RTC -> {BUZZ_SPOOF_AT:%H:%M:%S} (fire in {BUZZ_LEAD_SECONDS}s)", sent_at)

    print(f"  buzzer in ~{BUZZ_LEAD_SECONDS}s, then 10s of it. LISTEN -- {meaning}", flush=True)
    await asyncio.sleep(BUZZ_LEAD_SECONDS + BUZZ_TAIL_SECONDS)

    try:
        await client.experimental.timer_close(alarm)
        print("  buzz slot closed.", flush=True)
    except Exception as ex:
        print(f"  buzz slot close FAILED: {ex!r} -- cleanup will retry it", flush=True)


async def run_rung(client: IDotMatrixClient, log: AckLog, level: int, run: int) -> None:
    """Label the rung on the panel, set the state, THEN hold it still.

    The ack report happens before the hold deliberately: it sleeps ACK_SETTLE,
    which would otherwise eat into a plateau the meter is trying to log a steady
    value across. Once the hold starts, this probe sends nothing at all.
    """
    print(f"\n=== RUN {run}, brightness {level} -- scoreboard {level} | {run}", flush=True)
    await client.scoreboard.show(level, run)
    await asyncio.sleep(LABEL_SECONDS)

    sent_at = time.perf_counter()
    await client.device.set_brightness(level)
    await client.color.show(WHITE)
    await log.report(f"run {run} brightness {level} + white field", sent_at)

    print(f"  HOLD {HOLD_SECONDS}s: full white at {level}%. Nothing is sent during this.", flush=True)
    await asyncio.sleep(HOLD_SECONDS)


async def run_ladder(client: IDotMatrixClient, log: AckLog, run: int) -> None:
    """One complete 11-rung ladder. Identical in both runs -- only the sensor moves.

    Each rung is wrapped so a single failure cannot end the run: a ladder missing
    one rung still yields the 40:100 ratio the experiment turns on.
    """
    print(f"\n{'=' * 78}\nRUN {run}: {len(LADDER)} rungs, {LADDER[0]} -> {LADDER[-1]}\n{'=' * 78}", flush=True)
    for level in LADDER:
        try:
            await run_rung(client, log, level, run)
        except Exception as ex:
            print(f"  RUN {run} rung {level} FAILED: {ex!r}", flush=True)


async def intermission(client: IDotMatrixClient, log: AckLog, payload: bytes, armed: list[timer.Timer]) -> None:
    """Buzz, one minute of countdown, buzz -- then the true RTC back.

    Audible brackets because the operator is inside a light-tight chamber with
    their hands on the sensor and can see neither the panel nor the terminal.
    The countdown is stopped before the second buzz rather than left running:
    the native timer modes share device-side state (capabilities.py, 2026-07-20
    -- a paused countdown was seen hijacking chronograph commands), and an alarm
    firing over a live countdown is that same overlap.

    The RTC goes back to true time here, not just in cleanup, so the spoof is
    live for under two minutes of the run and never during a measurement.
    """
    try:
        await buzz(client, log, payload, armed, "START MOVING THE SENSOR NOW")
    except Exception as ex:
        print(f"  BUZZ 1 FAILED: {ex!r} -- ANNOUNCE THE MOVE SOME OTHER WAY", flush=True)

    try:
        print(f"\n--- {COUNTDOWN_MINUTES}-minute countdown on the panel (reposition the sensor now) ---", flush=True)
        sent_at = time.perf_counter()
        await client.countdown.start(COUNTDOWN_MINUTES, 0)
        await log.report("countdown start", sent_at)
        await asyncio.sleep(COUNTDOWN_MINUTES * 60)
        await client.countdown.stop()
        print("  countdown stopped.", flush=True)
    except Exception as ex:
        print(f"  COUNTDOWN FAILED: {ex!r} -- the buzzes still bracket the intermission", flush=True)

    try:
        await buzz(client, log, payload, armed, "RUN B RESUMING -- HANDS OFF THE SENSOR")
    except Exception as ex:
        print(f"  BUZZ 2 FAILED: {ex!r} -- run B starts in ~{ACK_SETTLE + LABEL_SECONDS:.0f}s anyway", flush=True)

    try:
        real_now = datetime.now()
        await client.device.set_time(real_now)
        print(f"  RTC back to true local time {real_now:%Y-%m-%d %H:%M:%S} before run B.", flush=True)
    except Exception as ex:
        print(f"  *** RTC restore before run B FAILED: {ex!r} -- cleanup will retry ***", flush=True)


async def restore(client: IDotMatrixClient, armed: list[timer.Timer]) -> None:
    """Leaves the panel in a state the operator can walk away from.

    Ordered by consequence, most damaging first, and each step guarded
    separately so one failure cannot cost the others. The true RTC leads: a
    stranded spoofed clock fires alarms at wrong wall-clock times and silently
    corrupts every later observation. The buzz slots come next -- armed for all
    seven days, one left open would beep at 12:01 every day indefinitely.
    """
    print("\n--- cleanup ---", flush=True)
    try:
        real_now = datetime.now()
        await client.device.set_time(real_now)
        print(f"restored: RTC -> true local time {real_now:%A %Y-%m-%d %H:%M:%S}", flush=True)
    except Exception as ex:
        print(
            f"*** RTC RESTORE FAILED: {ex!r} -- THE PANEL IS STILL ON A SPOOFED DATE."
            f" Fix it before trusting any later run. ***",
            flush=True,
        )

    for alarm in armed:
        try:
            await client.experimental.timer_close(alarm)
            print(f"restored: slot {alarm.num} closed", flush=True)
        except Exception as ex:
            print(
                f"*** SLOT {alarm.num} CLOSE FAILED: {ex!r} -- IT IS ARMED FOR"
                f" {alarm.hour:02d}:{alarm.minute:02d} EVERY DAY. Close it by hand. ***",
                flush=True,
            )

    for label, action in (
        ("countdown stopped", lambda: client.countdown.stop()),
        (f"brightness {PINNED}", lambda: client.device.set_brightness(PINNED)),
        ("clock", lambda: client.clock.show()),
    ):
        try:
            await action()
            print(f"restored: {label}", flush=True)
        except Exception as ex:
            print(f"*** RESTORE FAILED ({label}): {ex!r} -- CHECK THE PANEL BY HAND ***", flush=True)


def print_banner() -> None:
    """The operator's worksheet, printed before anything runs."""
    print("=" * 78, flush=True)
    print("BRIGHTNESS CURVE -- the same ladder, metered at TWO sensor distances.", flush=True)
    print("", flush=True)
    print("  RUN A: sensor at position 1 (tonight's geometry, ~2 inches).", flush=True)
    print("  INTERMISSION: buzzer -> 1-minute countdown -> buzzer. Move the sensor", flush=True)
    print("    FARTHER AWAY between the two buzzes -- roughly double the distance.", flush=True)
    print("    Change NOTHING else: not the room, the chamber, or the panel.", flush=True)
    print("  RUN B: the identical ladder at position 2.", flush=True)
    print("", flush=True)
    print(f"Ladder ({len(LADDER)} rungs): {', '.join(str(n) for n in LADDER)}", flush=True)
    print(f"Each rung: {LABEL_SECONDS}s scoreboard label (BRIGHTNESS | RUN), then {HOLD_SECONDS}s", flush=True)
    print("of a STEADY full-white field. Nothing is sent during a hold, so the log", flush=True)
    print("shows a flat plateau per rung with clean edges between them.", flush=True)
    print("", flush=True)
    print(
        f"THE MEASUREMENT IS A RATIO, NOT A VALUE: compute lux({RATIO_NUMERATOR}) / lux({RATIO_DENOMINATOR})",
        flush=True,
    )
    print("for EACH run. Distance scales every reading in a run by the same constant,", flush=True)
    print("so the ratio is distance-invariant if the sensor is honest.", flush=True)
    print("  both ratios ~0.95  => the panel's curve really is compressed.", flush=True)
    print("  near ~0.95, far ~0.4 => the near run was SENSOR SATURATION; it is void.", flush=True)
    print("=" * 78, flush=True)


async def main() -> None:
    print_banner()
    print("\nconnecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        log = AckLog()
        unsubscribe = client.add_response_listener(log.record)

        # Every slot this probe arms lands here the moment before it is uploaded,
        # so cleanup can close it even if the arming call raises partway through.
        armed: list[timer.Timer] = []
        buzz_payload = build_buzz_gif(client.screen_size.width)
        print(f"buzz payload built: {len(buzz_payload)}B", flush=True)

        try:
            # Known-state entry: reset (verified non-destructive), settle, then
            # the white field at the top of the ladder -- so run A's first rung
            # starts from a settled state rather than a transition.
            try:
                print("\nresetting device to a known state ...", flush=True)
                await client.device.reset()
                await asyncio.sleep(4)
                await client.device.set_brightness(PINNED)
                await client.color.show(WHITE)
                await asyncio.sleep(3)
                print(f"baseline: full-white field at {PINNED}%.", flush=True)
            except Exception as ex:
                print(f"  reset/baseline FAILED: {ex!r}", flush=True)

            await run_ladder(client, log, run=1)
            await intermission(client, log, buzz_payload, armed)
            await run_ladder(client, log, run=2)

            print("\nverdict to record (one lux plateau per rung, then two ratios):", flush=True)
            print(
                f"  ratio = lux({RATIO_NUMERATOR}) / lux({RATIO_DENOMINATOR}), computed"
                f" SEPARATELY for run 1 and run 2.",
                flush=True,
            )
            print("  both ~0.95      => panel compression is REAL; usable dimming is ~5-30 and", flush=True)
            print("                     the SDK should say so. eco_brightness above 40 is a no-op.", flush=True)
            print("  run1 ~0.95, run2 ~0.4 => run 1 was SENSOR SATURATION. Tonight's 3-point", flush=True)
            print("                     finding is VOID, and so is every reading taken at 2in,", flush=True)
            print("                     including P17b's calibration phases.", flush=True)
            print("  ratios differ, neither ~0.4 => partial saturation; quote the far run as a", flush=True)
            print("                     LOWER BOUND on compression, do not quote a curve.", flush=True)
            print("  also note: the first rung within a few percent of 100 (the practical top of", flush=True)
            print("  the range), whether 5/10/20 separate at all, and any NON-MONOTONIC rung.", flush=True)
        finally:
            # Runs even if a ladder or the intermission raised. The operator
            # spends the middle of this run away from the panel with their hands
            # in a chamber -- a probe that dies there must not leave a spoofed
            # clock and a daily alarm behind.
            unsubscribe()
            await restore(client, armed)
            print("done.", flush=True)


asyncio.run(main())
