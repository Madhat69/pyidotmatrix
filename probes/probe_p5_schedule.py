"""P5 -- Weekly Schedule verification: day-bit map, window boundaries, PNG themes.

WHY THIS PROBE EXISTS
---------------------
Schedule ("themes") is the last subsystem still carrying a warning flag. The
2026-07-12 session proved the per-theme chunked upload works (StatusAck SAVED)
and that a GIF theme DOES render inside its window, but left three holes:

  1. WHICH PHYSICAL DAY does a given week bit fire on? Schedule is the only
     feature that applies patch_week() -- protocol/schedule.py stores a RAW byte
     (bits0..6 = Mon..Sun, bit7 = "not repeating") and converts it on the wire to
     Timer's layout via ((week << 1) | 1) & 0xFF, i.e. [b6..b0, 1] with bit0
     pinned to the enabled flag. That is a source-traced ENCODING, never a
     hardware observation. Timer's own map WAS verified on hardware 2026-07-21
     (probes/probe_timer_weekbit.py) but Timer does not call patch(), so its
     result does not carry over -- a bug in patch_week would be invisible there.
  2. Is the window's END MINUTE inclusive or exclusive? The 2026-07-12 theme
     "ended ~1 min early", which reads as minute-EXCLUSIVE, but that was a
     side-observation, not a test (ROADMAP.md section 3 Alarms).
  3. Does a PNG (CONTENT_IMAGE) theme render? Schedule's image content is a
     genuine, source-confirmed asymmetry with Timer -- a PNG bytestream, not raw
     RGB (docs/APK_SECOND_PASS.md Q2). Never put on hardware.

METHOD -- RTC SPOOFING
----------------------
Same trick that mapped the Timer week bits in minutes (probes/probe_timer_weekbit
.py, 2026-07-21): the device evaluates its schedule against its OWN RTC, and
common.set_time owns that RTC -- spoofing the date flipped a day-masked Timer
from firing to silent, which is what proved the RTC's WEEKDAY follows set_time
and not just its wall clock. So no phase here waits for a real calendar day; the
whole run happens on a fabricated Wednesday and a fabricated Saturday.

Every device time in this probe is derived from ONE offset (spoofed base minus
real now) rather than by re-reading the clock, so the BLE time an upload spends
never desynchronizes the arithmetic: device_now() stays honest for the whole
phase and sleep_until() lands on the intended device minute.

WHY TWO DAYS ARE ENOUGH
-----------------------
The candidate encodings are all ROTATIONS of a 7-bit day field: "the bit we set
for weekday d actually means weekday d+k" for some fixed k (k = 0 is the
source-traced map; k = +-1 is the classic off-by-one from patch_week's shift;
any other k is a wholesale misread of the layout).

  * PHASE 1 arms ONLY Wednesday's bit and spoofs the RTC to a Wednesday. It
    fires only if k = 0. A single positive result therefore kills EVERY non-zero
    rotation at once -- no per-day sweep is needed.
  * PHASE 2 changes nothing but the RTC, to a Saturday. This kills the one
    hypothesis a positive cannot: that the mask is ignored / every-day. That is
    not a hypothetical -- the APK's own patch() has a probable off-by-one
    (`number + 255` instead of `+ 256`) that turns a 0x80 RAW byte into 0xFF,
    every day flagged; our port does not reproduce it, but firmware that
    ignores the mask entirely would look identical to a correct map in phase 1.

Wednesday (2) and Saturday (5) are deliberately NON-ADJACENT, so a +-1 rotation
cannot masquerade as a pass by leaking into phase 2's day either.

WHAT THE OPERATOR SEES
----------------------
The operator watches the panel, not stdout. Each phase opens with a scoreboard
label held 4 s -- count1 = PHASE NUMBER (1-4), count2 = EXPECTED OUTCOME
(1 = expect the theme's CONTENT, 0 = expect the CLOCK, 9 = a transition to
narrate). The panel is then returned to the clock as a neutral baseline, so
"fired" and "did not fire" are two obviously different pictures:

    FIRED (GIF theme)   -- the whole panel flashes MAGENTA <-> GREEN, ~3 Hz.
    FIRED (PNG theme)   -- a STATIC solid-blue panel with a thick white X. It
                           does not move at all; that stillness is the tell that
                           separates a rendered PNG from the GIF theme.
    DID NOT FIRE        -- the ordinary CLOCK face, unchanged, for the whole
                           watch window.

PHASE 3 IS DIFFERENT AND DELIBERATELY UNLABELLED MID-PHASE: once its theme is
armed, this probe sends NO display command until cleanup. A scoreboard or clock
command in the middle of a boundary test would be indistinguishable from the
window closing, which is the exact thing being measured. Phase 3 is therefore
ONE continuous ~4-minute observation and the docstring below lists, in order,
what should appear.

CRITICAL -- THE ACK BUG THIS PROBE DOES NOT REPRODUCE
-----------------------------------------------------
The 2026-07-26 night run (probe_effect_length_byte2.py) reported "no ack
whatsoever" for a whole class of frames and that finding had to be RETRACTED: it
printed its ack report immediately after the send, before the device's reply
(~0.3-4.3 s later) had arrived, then cleared the list at the phase boundary. So
here: every send is timestamped, followed by a mandatory ACK_SETTLE_SECONDS
(2.0 s) wait BEFORE the list is read, the list is cleared only AFTER it has been
printed, and each ack is printed with its send->ack DELTA. A zero-ack report
from this probe is evidence; one from that probe was not.

MANDATORY -- CLOCK RESTORATION GUARANTEE
----------------------------------------
This probe spoofs the device RTC to fabricated FUTURE dates. It restores the
true current time in a `finally` block that runs on EVERY exit path, including
an exception, a phase failure, or KeyboardInterrupt -- the restore is the FIRST
statement of that block, before any disarm or display work, so nothing that can
fail is allowed to run ahead of it. A panel left on a spoofed date fires alarms
at wrong wall-clock times and silently corrupts every later observation, so this
is treated as more important than the probe's own results.

DISARMING
---------
There is NO schedule equivalent of Timer's build_timer_close -- the Schedule
family has no close/disarm command at all. Cleanup therefore disarms by
OVERWRITING each theme it armed with week = build_schedule_week([]) (RAW 0x00,
patched 0x01: the enabled flag on, ZERO day bits, so no weekday can ever match)
over a degenerate 00:00-00:00 window, and then turns the master switch off.
Both themes this probe touches (index 0 and index 1) are overwritten, whether
or not their phase ran.

SAFETY
------
The three absolute exclusions are honoured: no set_password / verify_password
(lockout risk, no known factory reset), no write to the ae00/ae01 UART service
(OTA-adjacent surface on a Telink SoC, brick risk), and no
experimental.delete_device_data (destructive, irreversible, never
hardware-verified). common.reset() (04 00 03 80) is the verified-safe
known-state entry used by every recent probe.

The rest of client.experimental IS exercised here, deliberately:
schedule_set_theme and schedule_master_switch are the only Schedule API that
exists, and both are SOURCE_DERIVED in capabilities.py -- decompiled bytes never
confirmed on hardware. Moving them to VERIFIED (or KNOWN_BROKEN) is the point of
this probe.

READOUT
-------
  * P1 CONTENT + P2 CLOCK  => Schedule's day map is CONFIRMED as the source-traced
    one: RAW bit d = weekday d (Monday=0), patched bit d+1, bit0 = enabled. Every
    rotation is excluded by P1 and the mask-ignored case by P2. Promote
    schedule_set_theme's week mapping from source-derived to hardware-verified.
  * P1 CLOCK + P2 CLOCK    => the theme never fired at all. Do NOT read this as a
    day-map result: suspect the MASTER SWITCH first (schedule_master_switch's
    packed bit order, (buzzer << 1) | enable, is derived from a decompiled bit
    packer and has never been shown to actually gate anything). Retest with
    packed = 2 before touching the day-bit conclusion.
  * P1 CONTENT + P2 CONTENT => the day mask is IGNORED by this firmware, or
    patch_week's output is being read as every-day (the APK's +255 bug shape).
    Schedule themes are then effectively daily and GlanceOS must not offer
    per-day scheduling.
  * P1 CLOCK + P2 CONTENT  => the map is rotated, and by exactly the Wed->Sat
    distance. Re-derive patch_week; do not ship the current mapping.
  * P3 content still up 30 s INTO the end minute => the end boundary is minute-
    INCLUSIVE and the 2026-07-12 "ended a minute early" note was an artifact.
  * P3 content gone 30 s into the end minute, and the natural crossing shows it
    vanish at the START of the end minute => minute-EXCLUSIVE, confirming
    2026-07-12. A [T, T+2min] window is then 2 minutes long, not 3, and the SDK
    docs must say so.
  * P3's natural crossing tells us what the device falls back to the instant a
    window closes -- CLOCK is the expectation; a BLANK panel or a FROZEN last
    frame would each be a new, separate finding worth its own line.
  * P4 static blue/white X renders => Schedule CONTENT_IMAGE accepts an RGBA PNG,
    resolving the last untested content path. Promote it.
  * P4 SAVED ack but nothing renders => the same failure shape Timer's raw-RGB
    payload showed in 2026-07-12 (accepted, saved, never drawn). Next thing to
    try is a 3-channel RGB PNG (no alpha), since the DIY path's acceptance of
    RGBA is what motivated RGBA here.
  * P4 upload raises UploadError => the PNG is rejected outright, a different and
    more informative failure than a silent non-render; record the raw status.

USAGE
-----
    python probes/probe_p5_schedule.py

No arguments. Runtime ~12 minutes, of which ~11 are unattended watching; the
operator must be able to see the panel continuously from PHASE 3's label
onwards.

RESULT (2026-07-27): PARTIAL -- day-bit map and PNG themes CLOSED, window
boundary still OPEN.

  * PHASE 1 (Wednesday bit, RTC spoofed to Wednesday) fired the theme's
    content; PHASE 2 (same armed theme, RTC spoofed to the non-adjacent
    Saturday, nothing re-armed) stayed on the clock. Per the READOUT table
    this is CONTENT + CLOCK: Schedule's day-bit map is CONFIRMED as the
    source-traced encoding (RAW bit d = weekday d, Monday=0; patch_week's
    ((week << 1) | 1) & 0xFF wire conversion), the first hardware evidence
    for it, since Timer's own week-bit map does not call patch() and never
    covered this path. Every non-zero rotation of the day field and the
    mask-ignored/every-day hypothesis are both excluded by this pair.
  * PHASE 4 (PNG CONTENT_IMAGE theme) rendered the static blue-panel-with-
    white-X fixture inside its window -- CONFIRMED: Schedule accepts an RGBA
    PNG bytestream as theme content and actually draws it, resolving the
    last untested Schedule content path.
  * PHASE 3 (window end-boundary, inclusive vs. exclusive minute) did NOT
    reach a clean read this run. The continuous ~4-minute unlabelled watch
    this phase depends on is fragile in practice -- the same design this
    probe uses (arm, then send nothing until cleanup) makes it hard to
    separate "the window closed" from "something else interrupted the
    observation" after the fact. STILL OPEN; queued in docs/PROBE_PLAN.md as
    a redesigned boundary probe rather than a re-run of this one unchanged.

capabilities.py's experimental.schedule_set_theme entry is updated with the
day-bit and PNG results; the window-boundary claim from 2026-07-12 ("ended a
minute early") is left as-is pending the redesign.

RESOLVED 2026-07-27 by the redesigned probe: probes/probe_p5b_window_boundary.py
answered the boundary question this phase could not. The end minute is
INCLUSIVE, and Schedule evaluates on minute ticks rather than continuously
(see that probe's own RESULT block for the readout). The 2026-07-12
"ended a minute early" reading is OVERTURNED, not confirmed -- it was an
artifact of the minute-tick evaluation, not a real exclusive boundary.
capabilities.py's experimental.schedule_set_theme entry reflects this.
"""

import asyncio
import io
import time
from datetime import datetime, timedelta
from datetime import time as clock_time

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import schedule

ADDRESS = "6D:FD:F8:A0:3E:AF"

# Theme slots this probe owns. Both are overwritten with a no-day mask at
# cleanup regardless of which phases actually ran.
GIF_THEME_INDEX = 0
PNG_THEME_INDEX = 1

# Monday=0, matching datetime.weekday() and build_schedule_week. Non-adjacent on
# purpose -- see WHY TWO DAYS ARE ENOUGH.
HIT_WEEKDAY = 2   # Wednesday: the day whose bit gets armed
MISS_WEEKDAY = 5  # Saturday: same wall time, different day, nothing re-armed

# Read the ack list only after this long. The retracted 0x0d "ack silence"
# finding came from reading it immediately after the send -- see the docstring.
ACK_SETTLE_SECONDS = 2.0

LABEL_SECONDS = 4  # scoreboard hold: phase label AND phase boundary


def fake_datetime(weekday: int, hour: int, minute: int, second: int = 0) -> datetime:
    """A naive local datetime on the NEXT future date with the given weekday.

    Always a different calendar date from today (a same-weekday request lands a
    week out), so a crashed run can never leave the RTC on a date that merely
    looks plausible -- a wrong date is easier to notice than a wrong week.

    Naive on purpose: common.build_set_time converts a tz-AWARE datetime with
    .astimezone() and encodes a naive one unchanged as device-local wall time,
    which is exactly what a spoof wants.
    """
    today = datetime.now().date()
    days_ahead = (weekday - today.weekday()) % 7 or 7
    return datetime.combine(today + timedelta(days=days_ahead), clock_time(hour, minute, second))


def spoof_offset(base: datetime) -> timedelta:
    """The offset that makes device time read `base` right now."""
    return base - datetime.now()


def device_now(offset: timedelta) -> datetime:
    """What the device's spoofed RTC reads at this instant."""
    return datetime.now() + offset


def build_theme_gif(size: int) -> bytes:
    """2-frame MAGENTA <-> GREEN full-panel flash: the "theme is up" signal.

    RGB frames left to Pillow's own palettization, the encoding both
    protocol/gif.py's adapt_gif and the 2026-07-12 schedule probe use. A much
    earlier probe hand-built P-mode frames with putpalette() and displayed solid
    black on hardware because palette index 1 fell in the black half -- RGB
    frames sidestep that whole class of bug. optimize=True is required: without
    it the transfer breaks (see protocol/gif.py).
    """
    frame_a = Image.new("RGB", (size, size), (255, 0, 255))
    frame_b = Image.new("RGB", (size, size), (0, 255, 0))
    buffer = io.BytesIO()
    frame_a.save(buffer, format="GIF", save_all=True, optimize=True,
                 append_images=[frame_b], loop=0, duration=300, disposal=2)
    return buffer.getvalue()


def build_theme_png(size: int) -> bytes:
    """A STATIC blue panel with a thick white X, as an RGBA PNG.

    Static on purpose: motionlessness is what distinguishes "the PNG theme
    rendered" from "the GIF theme rendered" for an operator watching only the
    panel, and it cannot be confused with the clock face either.

    RGBA, fully opaque: Schedule's CONTENT_IMAGE is a single-frame PNG from the
    app's Bitmap.CompressFormat.PNG path (docs/APK_SECOND_PASS.md Q2), and
    Android bitmaps are ARGB_8888, so an alpha channel is what the app itself
    would emit; the DIY path is also known to accept RGBA PNG payloads. If this
    phase renders nothing, plain RGB is the next thing to try -- see READOUT.
    """
    image = Image.new("RGBA", (size, size), (0, 40, 200, 255))
    pixels = image.load()
    thickness = max(1, size // 10)
    for y in range(size):
        for x in range(size):
            on_main = abs(x - y) < thickness
            on_anti = abs(x + y - (size - 1)) < thickness
            if on_main or on_anti:
                pixels[x, y] = (255, 255, 255, 255)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def make_theme(index: int, weekdays: list[int], start: clock_time, end: clock_time) -> schedule.ScheduleTheme:
    """A ScheduleTheme carrying a RAW (pre-patch) week byte.

    build_schedule_theme_packets applies patch_week() itself, so this must NOT
    be pre-patched -- passing an already-patched byte would shift the day field
    a second time and is precisely the mistake this probe exists to detect.
    """
    return schedule.ScheduleTheme(
        index=index,
        week=schedule.build_schedule_week(weekdays),
        start_hour=start.hour,
        start_min=start.minute,
        end_hour=end.hour,
        end_min=end.minute,
    )


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        acks: list[tuple[float, str]] = []
        unsubscribe = client.add_response_listener(lambda ack: acks.append((time.perf_counter(), repr(ack))))

        def report_acks(label: str, sent_at: float) -> None:
            """Prints every ack captured since the last report, WITH its delta.

            Never call this without an ACK_SETTLE_SECONDS wait first, and note
            that the list is cleared only after printing: reading early and
            clearing at the phase boundary is exactly the instrumentation bug
            that produced a retracted finding on 2026-07-26.
            """
            if acks:
                print(f"  {label}: {len(acks)} ack(s):", flush=True)
                for stamp, text in acks:
                    print(f"    [send +{stamp - sent_at:.2f}s] {text}", flush=True)
                acks.clear()
            else:
                print(f"  {label}: *** ZERO ACKS after {ACK_SETTLE_SECONDS}s *** -- record this,"
                      f" it is a result (and this time it is a real one)", flush=True)

        async def send_and_report(label: str, coro) -> None:
            sent_at = time.perf_counter()
            await coro
            await asyncio.sleep(ACK_SETTLE_SECONDS)
            report_acks(label, sent_at)

        async def set_rtc(offset: timedelta, note: str) -> None:
            spoofed = device_now(offset)
            await send_and_report(f"set_time -> {spoofed:%A %Y-%m-%d %H:%M:%S} ({note})",
                                  client.common.set_time(spoofed))

        async def label_phase(number: int, expectation: int, text: str) -> None:
            """Scoreboard phase label, then back to the clock as the neutral
            baseline against which "fired" is visible."""
            print(f"\n=== PHASE {number} -- scoreboard {number} | {expectation} -- {text}", flush=True)
            await client.scoreboard.show(number, expectation)
            await asyncio.sleep(LABEL_SECONDS)
            await client.clock.show()

        async def sleep_until(offset: timedelta, target: datetime, what: str) -> None:
            seconds = (target - device_now(offset)).total_seconds()
            if seconds < 0:
                print(f"  !! already {-seconds:.0f}s PAST device-time {target:%H:%M:%S};"
                      f" this phase's timing is void", flush=True)
                return
            print(f"  waiting {seconds:.0f}s -> device-time {target:%H:%M:%S} ({what})", flush=True)
            await asyncio.sleep(seconds)

        gif_payload = build_theme_gif(client.screen_size.width)
        png_payload = build_theme_png(client.screen_size.width)
        print(f"payloads built: gif {len(gif_payload)}B, png {len(png_payload)}B", flush=True)

        try:
            # --- known-state entry -------------------------------------------
            try:
                print("resetting device to a known state ...", flush=True)
                await client.common.reset()
                await asyncio.sleep(4)
                await client.clock.show()
                await asyncio.sleep(3)
                acks.clear()
                print("baseline: clock. acks cleared.", flush=True)
            except Exception as ex:
                print(f"  reset/clock baseline FAILED: {ex!r}", flush=True)

            try:
                await send_and_report("master switch ON (buzzer off, keep it purely visual)",
                                      client.experimental.schedule_master_switch(enable=True, buzzer=False))
            except Exception as ex:
                print(f"  master switch FAILED: {ex!r} -- every later phase is now suspect", flush=True)

            # --- PHASE 1: day bit HIT ----------------------------------------
            # Arms Wednesday's bit ALONE and spoofs the RTC to a Wednesday. A
            # fire here excludes every rotation of the day field at once.
            try:
                await label_phase(1, 1, "Wednesday bit, RTC spoofed to Wednesday -- EXPECT CONTENT")
                offset = spoof_offset(fake_datetime(HIT_WEEKDAY, 12, 0, 0))
                await set_rtc(offset, "phase 1 base")

                theme = make_theme(GIF_THEME_INDEX, [HIT_WEEKDAY], clock_time(12, 1), clock_time(12, 4))
                print(f"  arming theme {GIF_THEME_INDEX}: RAW week=0b{theme.week:08b} ->"
                      f" patched 0b{schedule.patch_week(theme.week):08b}, window 12:01-12:04", flush=True)
                await send_and_report("theme upload (expect StatusAck status=3 SAVED)",
                                      client.experimental.schedule_set_theme(theme, gif_payload, schedule.CONTENT_GIF))

                await sleep_until(offset, fake_datetime(HIT_WEEKDAY, 12, 1, 0), "window opens")
                print("  WATCH (60s): MAGENTA/GREEN flash = FIRED. Clock face = DID NOT FIRE.", flush=True)
                await asyncio.sleep(60)
            except Exception as ex:
                print(f"  PHASE 1 FAILED: {ex!r}", flush=True)

            # --- PHASE 2: day bit MISS ---------------------------------------
            # Nothing is re-armed. The ONLY change is the RTC's weekday, so a
            # fire here means the mask is not being evaluated at all.
            try:
                await label_phase(2, 0, "same armed theme, RTC spoofed to Saturday -- EXPECT CLOCK")
                offset = spoof_offset(fake_datetime(MISS_WEEKDAY, 12, 0, 0))
                await set_rtc(offset, "phase 2 base -- theme deliberately NOT re-armed")

                await sleep_until(offset, fake_datetime(MISS_WEEKDAY, 12, 1, 0), "window would open")
                print("  WATCH (60s): clock face throughout = the day mask WORKS."
                      " Any magenta/green = the mask is IGNORED.", flush=True)
                await asyncio.sleep(60)
            except Exception as ex:
                print(f"  PHASE 2 FAILED: {ex!r}", flush=True)

            # --- PHASE 3: window end boundary --------------------------------
            # One continuous observation. NO display command is sent between the
            # arm and cleanup: a scoreboard or clock write mid-window is
            # indistinguishable from the window closing, which is the measurand.
            try:
                await label_phase(3, 9, "window boundary -- ONE CONTINUOUS 4min WATCH, narrate the order")
                offset = spoof_offset(fake_datetime(HIT_WEEKDAY, 12, 9, 0))
                await set_rtc(offset, "phase 3 base")

                theme = make_theme(GIF_THEME_INDEX, [HIT_WEEKDAY], clock_time(12, 10), clock_time(12, 12))
                print(f"  arming theme {GIF_THEME_INDEX}: window 12:10-12:12 (end minute = 12:12)", flush=True)
                await send_and_report("theme upload (boundary test)",
                                      client.experimental.schedule_set_theme(theme, gif_payload, schedule.CONTENT_GIF))

                print("  OPERATOR: from here until this phase ends, this probe sends NOTHING to the", flush=True)
                print("  display. Narrate, in order, what the panel does. Expected script:", flush=True)
                print("    (a) clock -> flash appears  [window opens at device 12:10]", flush=True)
                print("    (b) flash holds ~30s        [control: we are inside the window]", flush=True)
                print("    (c) RTC jumps 30s INTO the end minute 12:12 and holds 45s:", flush=True)
                print("          flash still up  => END MINUTE IS INCLUSIVE", flush=True)
                print("          clock instead   => END MINUTE IS EXCLUSIVE", flush=True)
                print("    (d) RTC jumps back to 12:11:40 and free-runs 100s across BOTH 12:12:00", flush=True)
                print("        and 12:13:00. Report WHICH crossing the flash disappeared on, and", flush=True)
                print("        exactly what replaced it (clock? blank panel? frozen last frame?).", flush=True)

                await sleep_until(offset, fake_datetime(HIT_WEEKDAY, 12, 10, 0), "window opens")
                await asyncio.sleep(30)  # (b) control: content must be up here

                # (c) the decisive binary read: 30 s inside the END minute.
                offset = spoof_offset(fake_datetime(HIT_WEEKDAY, 12, 12, 30))
                await set_rtc(offset, "jump to 30s INTO the end minute -- inclusive vs exclusive")
                await asyncio.sleep(45)

                # (d) natural crossing, so the fallback display can be seen.
                offset = spoof_offset(fake_datetime(HIT_WEEKDAY, 12, 11, 40))
                await set_rtc(offset, "jump back inside; free-run across 12:12:00 and 12:13:00")
                await asyncio.sleep(100)
            except Exception as ex:
                print(f"  PHASE 3 FAILED: {ex!r}", flush=True)

            # --- PHASE 4: PNG (CONTENT_IMAGE) theme --------------------------
            try:
                await label_phase(4, 1, "PNG image theme -- EXPECT a STATIC blue panel with a white X")
                offset = spoof_offset(fake_datetime(HIT_WEEKDAY, 12, 20, 0))
                await set_rtc(offset, "phase 4 base")

                theme = make_theme(PNG_THEME_INDEX, [HIT_WEEKDAY], clock_time(12, 21), clock_time(12, 24))
                print(f"  arming theme {PNG_THEME_INDEX} as CONTENT_IMAGE, {len(png_payload)}B RGBA PNG,"
                      f" window 12:21-12:24", flush=True)
                await send_and_report(
                    "PNG theme upload (expect StatusAck status=3 SAVED)",
                    client.experimental.schedule_set_theme(theme, png_payload, schedule.CONTENT_IMAGE),
                )

                await sleep_until(offset, fake_datetime(HIT_WEEKDAY, 12, 21, 0), "window opens")
                print("  WATCH (75s): STATIC blue + white X = PNG themes RENDER. Clock = SAVED but", flush=True)
                print("  never drawn (Timer's raw-RGB failure shape). Anything ANIMATED means the", flush=True)
                print("  device is still showing phase 3's GIF theme -- record that instead.", flush=True)
                await asyncio.sleep(75)
            except Exception as ex:
                print(f"  PHASE 4 FAILED: {ex!r}", flush=True)

        finally:
            # RESTORATION GUARANTEE. The true clock goes back FIRST, before any
            # disarm or display work, so nothing that can fail runs ahead of it.
            print("\n--- cleanup ---", flush=True)
            try:
                real_now = datetime.now()
                await client.common.set_time(real_now)
                print(f"RTC RESTORED to true local time {real_now:%A %Y-%m-%d %H:%M:%S}.", flush=True)
            except Exception as ex:
                print(f"*** RTC RESTORE FAILED: {ex!r} -- THE PANEL IS STILL ON A SPOOFED DATE."
                      f" Re-run any probe that calls common.set_time before trusting it. ***", flush=True)

            # No Schedule close command exists; overwrite with a mask no weekday
            # can match (RAW 0x00 -> patched 0x01: enabled flag, zero day bits).
            for index in (GIF_THEME_INDEX, PNG_THEME_INDEX):
                try:
                    dead = make_theme(index, [], clock_time(0, 0), clock_time(0, 0))
                    await client.experimental.schedule_set_theme(dead, gif_payload, schedule.CONTENT_GIF)
                    print(f"theme {index} disarmed (RAW week=0x00 -> patched"
                          f" 0b{schedule.patch_week(dead.week):08b}, no day bits).", flush=True)
                except Exception as ex:
                    print(f"theme {index} disarm FAILED: {ex!r}", flush=True)

            try:
                await client.experimental.schedule_master_switch(enable=False, buzzer=False)
                print("schedule master switch OFF.", flush=True)
            except Exception as ex:
                print(f"master switch off FAILED: {ex!r}", flush=True)

            try:
                unsubscribe()
                await client.clock.show()
                print("clock restored. done.", flush=True)
            except Exception as ex:
                print(f"final clock.show FAILED: {ex!r}", flush=True)


asyncio.run(main())
