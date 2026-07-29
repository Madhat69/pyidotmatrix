"""P5b -- Schedule window END BOUNDARY: is the end minute inclusive or exclusive?

ONE QUESTION
------------
A schedule theme armed for the window 12:10-12:12 is either still showing its
content at device-time 12:12:30, or it is not.

    content visible at 12:12:30  =>  the end minute is INCLUSIVE
                                     ([12:10, 12:12] is a 3-minute window)
    clock face at 12:12:30       =>  the end minute is EXCLUSIVE
                                     ([12:10, 12:12) is a 2-minute window)

That is the whole probe. Nothing else is measured.

WHY THIS EXISTS (the predecessor's phase 3 failed as a DESIGN)
--------------------------------------------------------------
probes/probe_p5_schedule.py ran on 2026-07-26. Its phases 1, 2 and 4 are
SETTLED and are not repeated here:

  * Day-bit map CONFIRMED. A theme armed with RAW week 0b00000100 -> patched
    0b00001001 fired on a spoofed Wednesday, and the SAME armed theme did NOT
    fire on a spoofed Saturday. Monday=RAW bit0, bit0 of the patched byte is the
    enabled flag, exactly as protocol/schedule.py's patch_week claims.
  * PNG (CONTENT_IMAGE) themes RENDER (static blue panel, white X).

Its phase 3 -- this question -- did not fail on the hardware, it failed on
paper. It packed FOUR RTC jumps into a single silent four-minute window and
asked the operator to keep track of a device clock they could only infer from a
clock face that kept jumping underneath them. Operator verdict: "this one is
complex as fuck... it was a mess. We need to break this one into smaller
chunks." Their partial account of that phase is UNUSABLE and must not be cited
as evidence either way. So the 2026-07-12 side-observation that a theme "ended
~1 min early" -- which reads as minute-EXCLUSIVE -- is still unproven.

This probe is the smaller chunk: ONE arm, ONE jump, ONE observation, one run.

TWO MODES -- RUN BOTH, `control` FIRST
--------------------------------------
    python probes/probe_p5b_window_boundary.py control
    python probes/probe_p5b_window_boundary.py test

  * `control` arms the identical 12:10-12:12 theme and jumps the RTC to
    12:11:30 -- comfortably INSIDE the window. Content MUST appear. This mode
    answers nothing about the boundary; it exists so that a blank result from
    `test` can be told apart from "the theme never fired at all". If `control`
    shows the clock, `test` proves NOTHING and must not be interpreted.
  * `test` arms the same theme and jumps the RTC to 12:12:30 -- thirty seconds
    INTO the end minute. This is the measurement.

No argument prints usage and exits non-zero, so neither run can happen by
accident and neither mode can be run believing it was the other one.

WHAT THE OPERATOR SEES -- THE PANEL IS THE ONLY INSTRUMENT
----------------------------------------------------------
The operator cannot see stdout. Everything the observation turns on must be
answerable by looking at the panel alone, so the two outcomes are deliberately
nothing alike:

    FIRED         -- the WHOLE panel flashes MAGENTA <-> GREEN at about 3 Hz.
                     Unmistakable; it is not a picture, it is the panel
                     strobing between two saturated colours.
    DID NOT FIRE  -- the ordinary CLOCK face, unchanged, for the whole watch.

The run opens with a scoreboard label (held 4 s) so the operator knows which
mode is on the panel in front of them -- 1|1 for `control` (expect content),
2|0 for `test` (the open question, clock is the null result) -- and then returns
the panel to the CLOCK as a neutral baseline. From the moment the theme is armed
until cleanup, this probe sends NOTHING to the display. A scoreboard or clock
write mid-observation is indistinguishable from the window closing, and the
window closing is the measurand.

RTC SPOOFING
------------
Same trick as probe_timer_weekbit.py / probe_p5_schedule.py: the device
evaluates schedules against its own RTC and common.set_time owns that RTC, so
no calendar waiting is needed. Every device time is derived from ONE offset
(spoofed base minus real now), never by re-reading the clock, so BLE upload time
cannot desynchronize the arithmetic.

MANDATORY CLEANUP
-----------------
The `finally` block restores the TRUE local time FIRST, ahead of anything that
could fail, then disarms the theme, then the master switch, then the clock. It
runs on the failure path and on KeyboardInterrupt too. A panel left on a spoofed
future date fires alarms at wrong wall-clock times and silently corrupts every
later observation, which matters more than this probe's own result.

Schedule has NO close/disarm command, so disarming means OVERWRITING theme 0
with RAW week 0x00 (patched 0b00000001: enabled flag set, ZERO day bits, no
weekday can ever match) over a degenerate 00:00-00:00 window.

ACK REPORTING
-------------
Every send is timestamped and followed by a mandatory ACK_SETTLE_SECONDS (2.0 s)
wait BEFORE the ack list is read; the list is cleared only AFTER it is printed.
Reading early and clearing at a phase boundary is the instrumentation bug that
forced a retraction on 2026-07-26.

SAFETY
------
Standing exclusions honoured: no set_password / verify_password, no writes to
the ae00/ae01 UART service, no experimental.delete_device_data.

RESULT (2026-07-27): ANSWERED -- the end minute is INCLUSIVE, and evaluation
happens on MINUTE TICKS, not continuously.

  * `control` (RTC jumped to 12:11:30, inside the window): the jump itself
    fired NOTHING -- landing mid-window via set_time does not trigger the
    schedule check. Content appeared once the device's own spoofed clock
    naturally rolled over to the next minute, 12:12:00, and held. This is a
    NEW finding beyond the boundary question: Schedule is evaluated at minute
    rollovers, not on every RTC write or continuously against wall time.
  * `test` (RTC jumped to 12:12:30, 30s into the end minute): no content
    appeared at the jump either (consistent with minute-tick evaluation), and
    the watch continued across the next tick, 12:13:00, with the panel still
    on the clock -- the window is closed by 12:13.
  * Read together: the window covers 12:10, 12:11 and 12:12 -- the end
    minute IS INCLUSIVE. This OVERTURNS the 2026-07-12 "ended ~1 min early"
    / minute-exclusive reading: that observation was an artifact of the same
    minute-tick evaluation this probe uncovered, not a genuinely exclusive
    boundary. Do not record 2026-07-12's reading as correct in any future
    doc pass.

capabilities.py's experimental.schedule_set_theme entry is updated with this
result, replacing the "STILL OPEN" boundary note left by probe_p5_schedule.py.
"""

import asyncio
import io
import sys
import time
from datetime import datetime, timedelta
from datetime import time as clock_time

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import schedule

ADDRESS = "6D:FD:F8:A0:3E:AF"

THEME_INDEX = 0

# Monday=0, matching datetime.weekday() and build_schedule_week. Wednesday is
# the day whose bit was CONFIRMED to fire on 2026-07-26; reusing it keeps the
# day map out of the picture entirely.
HIT_WEEKDAY = 2

WINDOW_START = clock_time(12, 10)
WINDOW_END = clock_time(12, 12)

# The RTC lands here before the theme is armed: same spoofed Wednesday, safely
# BEFORE the window, so the arm itself never straddles a boundary.
ARM_HOUR, ARM_MIN = 12, 5

# The single jump, per mode. `test` is 30 s into the END minute -- the whole
# question. `control` is 30 s into the middle minute -- unambiguously inside.
JUMP_SECONDS = {"test": (12, 12, 30), "control": (12, 11, 30)}

OBSERVE_SECONDS = 60
LABEL_SECONDS = 4
ACK_SETTLE_SECONDS = 2.0


def usage() -> None:
    print(__doc__.strip().splitlines()[0], flush=True)
    print("\nusage: python probes/probe_p5b_window_boundary.py {control|test}\n", flush=True)
    print("  control  RTC -> 12:11:30, inside the 12:10-12:12 window. Content MUST appear.", flush=True)
    print("           Run this FIRST. If it shows the clock, `test` proves nothing.", flush=True)
    print("  test     RTC -> 12:12:30, 30s into the END minute. Content = INCLUSIVE, clock = EXCLUSIVE.", flush=True)


def fake_datetime(weekday: int, hour: int, minute: int, second: int = 0) -> datetime:
    """A naive local datetime on the NEXT future date with the given weekday.

    Always a different calendar date from today, so a crashed run can never
    leave the RTC on a date that merely looks plausible. Naive on purpose:
    common.build_set_time encodes a naive datetime unchanged as device-local
    wall time, which is exactly what a spoof wants.
    """
    today = datetime.now().date()
    days_ahead = (weekday - today.weekday()) % 7 or 7
    return datetime.combine(today + timedelta(days=days_ahead), clock_time(hour, minute, second))


def build_theme_gif(size: int) -> bytes:
    """2-frame MAGENTA <-> GREEN full-panel flash: the "the theme is up" signal.

    RGB frames, palettized by Pillow. optimize=True is required or the transfer
    breaks (see protocol/gif.py). Hand-built P-mode frames displayed solid black
    on hardware in an earlier probe; RGB sidesteps that class of bug.
    """
    frame_a = Image.new("RGB", (size, size), (255, 0, 255))
    frame_b = Image.new("RGB", (size, size), (0, 255, 0))
    buffer = io.BytesIO()
    frame_a.save(
        buffer, format="GIF", save_all=True, optimize=True, append_images=[frame_b], loop=0, duration=300, disposal=2
    )
    return buffer.getvalue()


def make_theme(weekdays: list[int], start: clock_time, end: clock_time) -> schedule.ScheduleTheme:
    """A ScheduleTheme carrying a RAW (pre-patch) week byte.

    build_schedule_theme_packets applies patch_week() itself, so this must NOT
    be pre-patched -- a pre-patched byte would shift the day field twice.
    """
    return schedule.ScheduleTheme(
        index=THEME_INDEX,
        week=schedule.build_schedule_week(weekdays),
        start_hour=start.hour,
        start_min=start.minute,
        end_hour=end.hour,
        end_min=end.minute,
    )


async def main(mode: str) -> None:
    jump_hour, jump_min, jump_sec = JUMP_SECONDS[mode]
    label = 1 if mode == "control" else 2
    expectation = 1 if mode == "control" else 0

    print(f"MODE: {mode}", flush=True)
    if mode == "control":
        print(
            "QUESTION: does the armed 12:10-12:12 theme show its content at 12:11:30, i.e. does it fire at all?",
            flush=True,
        )
        print("EXPECT: magenta/green flash. A clock face here voids the `test` run.", flush=True)
    else:
        print(
            "QUESTION: is the armed 12:10-12:12 theme still showing its content at 12:12:30, 30s into the END minute?",
            flush=True,
        )
        print("EXPECT: unknown -- flash = end minute INCLUSIVE, clock = end minute EXCLUSIVE.", flush=True)
    print(f"panel scoreboard will read {label} | {expectation}. Watch the panel, not this terminal.\n", flush=True)

    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        acks: list[tuple[float, str]] = []
        unsubscribe = client.add_response_listener(lambda ack: acks.append((time.perf_counter(), repr(ack))))

        def report_acks(what: str, sent_at: float) -> None:
            """Prints every ack captured since the last report, WITH its delta.

            Never call without an ACK_SETTLE_SECONDS wait first; the list is
            cleared only after printing.
            """
            if acks:
                print(f"  {what}: {len(acks)} ack(s):", flush=True)
                for stamp, text in acks:
                    print(f"    [send +{stamp - sent_at:.2f}s] {text}", flush=True)
                acks.clear()
            else:
                print(f"  {what}: ZERO ACKS after {ACK_SETTLE_SECONDS}s.", flush=True)

        async def send_and_report(what: str, coro) -> None:
            sent_at = time.perf_counter()
            await coro
            await asyncio.sleep(ACK_SETTLE_SECONDS)
            report_acks(what, sent_at)

        gif_payload = build_theme_gif(client.screen_size.width)
        print(f"payload built: gif {len(gif_payload)}B", flush=True)

        try:
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

            try:
                await send_and_report(
                    "master switch ON (buzzer off, keep it purely visual)",
                    client.experimental.schedule_master_switch(enable=True, buzzer=False),
                )
            except Exception as ex:
                print(f"  master switch FAILED: {ex!r} -- the observation is now suspect", flush=True)

            try:
                print(f"\n=== label: scoreboard {label} | {expectation}", flush=True)
                await client.scoreboard.show(label, expectation)
                await asyncio.sleep(LABEL_SECONDS)
                await client.clock.show()
            except Exception as ex:
                print(f"  label FAILED: {ex!r}", flush=True)

            # --- arm, on the spoofed Wednesday, BEFORE the window opens ------
            try:
                base = fake_datetime(HIT_WEEKDAY, ARM_HOUR, ARM_MIN, 0)
                await send_and_report(
                    f"set_time -> {base:%A %Y-%m-%d %H:%M:%S} (pre-window base)", client.device.set_time(base)
                )

                theme = make_theme([HIT_WEEKDAY], WINDOW_START, WINDOW_END)
                print(
                    f"  arming theme {THEME_INDEX}: RAW week=0b{theme.week:08b} ->"
                    f" patched 0b{schedule.patch_week(theme.week):08b},"
                    f" window {WINDOW_START:%H:%M}-{WINDOW_END:%H:%M}",
                    flush=True,
                )
                await send_and_report(
                    "theme upload (expect StatusAck status=3 SAVED)",
                    client.experimental.schedule_set_theme(theme, gif_payload, schedule.CONTENT_GIF),
                )
            except Exception as ex:
                print(f"  ARM FAILED: {ex!r} -- do not interpret the observation", flush=True)

            # --- the one jump, then the one observation ----------------------
            # Nothing is sent to the display from here until cleanup: a display
            # command mid-observation is indistinguishable from the window
            # closing, which is the measurand.
            try:
                jump = fake_datetime(HIT_WEEKDAY, jump_hour, jump_min, jump_sec)
                print(f"\n=== OBSERVE ({OBSERVE_SECONDS}s). Jumping RTC to {jump:%H:%M:%S}, then silence.", flush=True)
                if mode == "control":
                    print("  FLASH = fired (expected). CLOCK = it never fired; the `test` run is void.", flush=True)
                else:
                    print("  FLASH = end minute INCLUSIVE. CLOCK = end minute EXCLUSIVE.", flush=True)
                # 2026-07-26: set_time calls issued WHILE a schedule theme was
                # firing drew ZERO acks, where every other set_time in that
                # session drew two. Unexplained and not built on here -- just do
                # not read a silent set_time as a failed one.
                await send_and_report(f"set_time -> {jump:%H:%M:%S} (the single jump)", client.device.set_time(jump))
                await asyncio.sleep(OBSERVE_SECONDS)
            except Exception as ex:
                print(f"  OBSERVATION FAILED: {ex!r}", flush=True)

        finally:
            # RESTORATION GUARANTEE. True clock first, ahead of anything that
            # can fail.
            print("\n--- cleanup ---", flush=True)
            try:
                real_now = datetime.now()
                await client.device.set_time(real_now)
                print(f"RTC RESTORED to true local time {real_now:%A %Y-%m-%d %H:%M:%S}.", flush=True)
            except Exception as ex:
                print(
                    f"*** RTC RESTORE FAILED: {ex!r} -- THE PANEL IS STILL ON A SPOOFED DATE."
                    f" Re-run any probe that calls common.set_time before trusting it. ***",
                    flush=True,
                )

            # No Schedule close command exists; overwrite with a mask no weekday
            # can match (RAW 0x00 -> patched 0b00000001) over a zero-width window.
            try:
                dead = make_theme([], clock_time(0, 0), clock_time(0, 0))
                await client.experimental.schedule_set_theme(dead, gif_payload, schedule.CONTENT_GIF)
                print(
                    f"theme {THEME_INDEX} disarmed (RAW week=0x00 -> patched"
                    f" 0b{schedule.patch_week(dead.week):08b}, no day bits).",
                    flush=True,
                )
            except Exception as ex:
                print(f"theme {THEME_INDEX} disarm FAILED: {ex!r}", flush=True)

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


# Parsed before any BLE contact: a mistyped or missing mode must not connect.
if len(sys.argv) != 2 or sys.argv[1] not in JUMP_SECONDS:
    usage()
    raise SystemExit(2)

asyncio.run(main(sys.argv[1]))
