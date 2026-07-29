"""P19 G4 -- does an ARMED SCHEDULE THEME silence set_time's acks?

WHY THIS PROBE EXISTS
---------------------
Two recorded results contradict each other:

  * P14 (probes/probe_p14_ack_timing.py, 2026-07-27) calibrated seven command
    families, five repeats each, and found NO family silent. That is the
    sentence capabilities.py's common.ack_timing has been carrying, and the
    sentence transport.await_device_ack's 2.0 s default is designed against.
  * P5 (probes/probe_p5_schedule.py, same day) saw common.set_time draw TWO
    acks per call while the schedule subsystem was idle, and then ZERO acks --
    three calls running -- once a schedule theme had been armed. Same 2.0 s
    settle as everything else in that probe, so this is genuine silence and not
    the 2026-07-26 read-the-list-too-early instrumentation bug.

P14 never tested set_time, and it never ran with a theme armed, so the two
results do not actually collide -- but nobody can tell that from the docs. The
consequence is concrete: a caller that awaits a reply for set_time (anything
routing it through a response=True path) would HANG on a device with an armed
schedule theme. The SDK does not await one today. Before that is written down as
safe, the effect needs to be reproduced deliberately.

THE MEASUREMENT
---------------
Three set_time jumps WITH a theme armed, three with nothing armed, ack counts
side by side in one table. Everything else is held identical: same fabricated
day, same three target times, same settle, same order.

    ARMED half     master switch ON, theme 0 armed for the spoofed weekday over
                   a 12:10-12:12 window, then jumps to 12:09, 12:11, 12:13 --
                   before / inside / after the window. Those are P5's own
                   conditions, boundary crossings and all, because the zero-ack
                   observation came from exactly that shape of run.
    CONTROL half   theme 0 and 1 overwritten with a no-day mask, master switch
                   OFF, then the SAME three jumps.

    ARMED 0 acks, CONTROL 2 acks each   => REPRODUCED. Armed schedule state
                                           suppresses set_time's reply; scope
                                           P14's "never silent" accordingly and
                                           warn callers off awaiting one.
    BOTH halves ack                     => P5's observation does not reproduce
                                           on this axis. Look elsewhere (in-
                                           window vs out-of-window? the master
                                           switch alone? upload proximity?) and
                                           leave the P14 claim standing.
    BOTH halves silent                  => the variable is not the theme at all
                                           but set_time itself under some
                                           condition P14 never hit; a much
                                           bigger correction, and worth saying
                                           so loudly.

RTC SPOOFING, AND THE RESTORATION GUARANTEE
-------------------------------------------
This probe writes the device RTC -- that is the command under test. Every device
time is derived from ONE offset (spoofed base minus real now), as in P5, so the
BLE time a jump spends never desynchronizes the arithmetic. The TRUE local time
is restored in a `finally` block that runs on EVERY exit path including an
exception or KeyboardInterrupt, and the restore is the FIRST statement of that
block, ahead of any disarm or display work, so nothing that can fail runs before
it. A panel left on a spoofed date fires alarms at wrong wall-clock times and
silently corrupts every later observation.

DISARMING
---------
There is no schedule close command. Cleanup overwrites BOTH theme slots this
probe could touch with week = build_schedule_week([]) (RAW 0x00, patched 0x01:
enabled flag on, zero day bits, so no weekday can match) over a degenerate
00:00-00:00 window, then turns the master switch off -- P5's disarm, unchanged.
It runs whether or not the armed half ran.

ACK DISCIPLINE
--------------
Every send is timestamped, waits SETTLE_SECONDS (2.5 s) BEFORE the ack list is
read, and is reported with its send->ack delta. The list is NEVER cleared: each
step reports only the slice since its own mark, so a late reply lands in a later
step's report rather than being destroyed. Ack counts are what this probe
measures, so the discipline is the probe.

SAFETY
------
No set_password / verify_password, no ae00 / ae01 UART write, no
experimental.delete_device_data. schedule_set_theme and schedule_master_switch
ARE exercised -- they are the only Schedule API there is, and P5 established
both on hardware.

USAGE
-----
    python probes/probe_p19_g4_settime_acks.py full      # armed half, then control half
    python probes/probe_p19_g4_settime_acks.py armed     # armed half only
    python probes/probe_p19_g4_settime_acks.py control   # control half only

The argument is mandatory and selects exactly one sequence. `full` is the run
that answers the question; the single halves exist for a re-check of one side
without paying for the other. Runtime ~2 min for `full`.

RESULT (2026-07-28, `full`): THE THIRD BRANCH -- BOTH HALVES SILENT.

    jump                    ARMED   CONTROL
    J1 before the window      0        0
    J2 inside the window      0        0
    J3 after the window       0        0

Plus the pre-arm jump this probe makes before arming anything: also 0. Seven
observations, every one silent, at the 2.5 s settle with the ack list never read
early and never cleared -- the instrumentation bug class that produced earlier
false zero-ack findings is excluded by construction.

THE ARMED-SCHEDULE HYPOTHESIS IS FALSIFIED. The control half was genuinely
unarmed (both theme slots overwritten, StatusAck 3 each, master switch OFF) and
set_time was silent there too. `set_time` simply never acks on this panel.

P5's contrary two-ack reading is the lone outlier against these seven and is
recorded as SUPERSEDED -- most probably an ack-attribution artifact, acks from
neighbouring commands landing in its measurement window, which is the same
failure class corrected elsewhere in that session. PROBABLE, not established.

NOT a hang hazard: transport.await_device_ack returns None on a bounded timeout
by design. But it cost the FULL _DEFAULT_ACK_TIMEOUT (2.0 s, transport/ble.py)
on every call, and set_time is typically a caller's first write of every
connection -- so every startup, reconnect and self-heal silently paid it.
CONSEQUENCE, implemented: IDotMatrixClient.device.set_time is now fire-and-
forget (verify=False), alongside graffiti and verify_password. Full account in
capabilities.py's device.set_time and device.ack_timing.
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
SCREEN = ScreenSize.SIZE_32x32

# Theme slots this probe owns. Both are overwritten at cleanup regardless of
# which half ran -- P5's convention, so the two probes cannot leave each other
# a live theme.
GIF_THEME_INDEX = 0
SPARE_THEME_INDEX = 1

HIT_WEEKDAY = 2  # Wednesday, Monday=0, matching datetime.weekday()

# The window the armed half arms, and the three times it jumps to: one before,
# one INSIDE, one after. P5's shape, where the zero-ack runs were seen.
WINDOW_START = clock_time(12, 10)
WINDOW_END = clock_time(12, 12)
JUMPS: tuple[tuple[str, clock_time, str], ...] = (
    ("J1 before the window", clock_time(12, 9), "clock face"),
    ("J2 INSIDE the window", clock_time(12, 11), "MAGENTA/GREEN flash (armed half only)"),
    ("J3 after the window", clock_time(12, 13), "clock face"),
)

SETTLE_SECONDS = 2.5  # read the ack list only after this long, never before
WATCH_SECONDS = 6.0   # after each jump, so a window crossing is actually visible

SEQUENCES = {
    "full": "armed half, then control half -- the run that answers the question",
    "armed": "armed half only (theme armed, three jumps)",
    "control": "control half only (nothing armed, three jumps)",
}


def print_usage() -> None:
    print("usage: python probes/probe_p19_g4_settime_acks.py <sequence>", flush=True)
    print("", flush=True)
    print("Runs exactly ONE sequence. The argument is mandatory.", flush=True)
    for key, description in SEQUENCES.items():
        print(f"    {key:8s} {description}", flush=True)


def select_sequence(argv: list[str]) -> str:
    """Validated before any BLE contact, so a typo cannot spoof the RTC."""
    if not argv:
        print("error: a sequence name is required.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    if len(argv) > 1:
        print(f"error: expected exactly one sequence name, got {len(argv)}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    if argv[0] not in SEQUENCES:
        print(f"error: unrecognized sequence {argv[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    return argv[0]


def print_visual_script(sequence: str) -> None:
    """EVERY visual of the run, in order, before any BLE contact.

    Exhaustive INCLUDING the baseline. An operator who is not told about a
    baseline frame sees their first visual contradict their brief and stops
    trusting the run -- the single biggest cause of a wasted panel session here.
    """
    runs_armed = sequence in ("full", "armed")
    runs_control = sequence in ("full", "control")
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER =============================================", flush=True)
    print("  0. BASELINE: the ordinary CLOCK FACE, sent once at the start so every later", flush=True)
    print("     visual has something neutral to change away from. Not a measurement.", flush=True)
    print("     NOTE: the clock will read a FABRICATED date and time for most of this", flush=True)
    print("     run -- around 12:09-12:13 on a future Wednesday. That is deliberate;", flush=True)
    print("     the true time is restored at the end, on every exit path.", flush=True)
    if runs_armed:
        print("  1. ARMED HALF -- a theme is uploaded (no visible change during upload),", flush=True)
        print("     then three RTC jumps, each held ~6 s:", flush=True)
        print("       1a. jump to 12:09 -- BEFORE the window: the CLOCK FACE.", flush=True)
        print("       1b. jump to 12:11 -- INSIDE the window: the whole panel flashing", flush=True)
        print("           MAGENTA <-> GREEN, ~3 Hz. This one is SUPPOSED to look different.", flush=True)
        print("       1c. jump to 12:13 -- AFTER the window: back to the CLOCK FACE.", flush=True)
    if runs_control:
        print("  2. CONTROL HALF -- the theme is disarmed and the master switch goes off,", flush=True)
        print("     then the SAME three jumps, each held ~6 s. The panel should show the", flush=True)
        print("     ORDINARY CLOCK FACE for all three, INCLUDING the 12:11 one. If the", flush=True)
        print("     magenta/green flash appears again here, the disarm did not take and", flush=True)
        print("     the control half is void -- say so.", flush=True)
    print("  3. CLEANUP: the true date and time go back, both theme slots are overwritten", flush=True)
    print("     with a mask no weekday can match, the master switch goes off, and the", flush=True)
    print("     panel is left on the ordinary CLOCK FACE showing the REAL time.", flush=True)
    print("", flush=True)
    print("  YOU DO NOT HAVE TO READ ANYTHING OFF THE PANEL. The measurement is ack", flush=True)
    print("  counts, printed on the console. This panel's clock shows hours and minutes", flush=True)
    print("  only, with NO SECONDS -- never try to time a jump by watching it.", flush=True)
    print("  All you are asked to confirm is whether 1b flashed and whether 2 stayed on", flush=True)
    print("  the clock; that is what says the theme really was armed and really was", flush=True)
    print("  disarmed.", flush=True)
    print("=============================================================================", flush=True)


def build_theme_gif(size: int) -> bytes:
    """2-frame MAGENTA <-> GREEN full-panel flash -- P5's "the theme is up" signal.

    RGB frames left to Pillow's own palettization (a hand-built P-mode fixture
    once displayed solid black on this panel), and optimize=True, which
    protocol/gif.py requires.
    """
    frame_a = Image.new("RGB", (size, size), (255, 0, 255))
    frame_b = Image.new("RGB", (size, size), (0, 255, 0))
    buffer = io.BytesIO()
    frame_a.save(buffer, format="GIF", save_all=True, optimize=True,
                 append_images=[frame_b], loop=0, duration=300, disposal=2)
    return buffer.getvalue()


def fake_datetime(weekday: int, at: clock_time) -> datetime:
    """A naive local datetime on the NEXT future date with the given weekday.

    Always a different calendar date from today, so a crashed run cannot leave
    the RTC on a date that merely looks plausible. Naive on purpose:
    common.build_set_time encodes a naive datetime unchanged as device-local
    wall time, which is what a spoof wants.
    """
    today = datetime.now().date()
    days_ahead = (weekday - today.weekday()) % 7 or 7
    return datetime.combine(today + timedelta(days=days_ahead), at)


def make_theme(index: int, weekdays: list[int], start: clock_time, end: clock_time) -> schedule.ScheduleTheme:
    """A ScheduleTheme carrying a RAW (pre-patch) week byte.

    build_schedule_theme_packets applies patch_week() itself, so this must NOT
    be pre-patched -- double-patching shifts the day field twice.
    """
    return schedule.ScheduleTheme(
        index=index,
        week=schedule.build_schedule_week(weekdays),
        start_hour=start.hour,
        start_min=start.minute,
        end_hour=end.hour,
        end_min=end.minute,
    )


async def main(sequence: str) -> None:
    print(f"sequence: {sequence} -- {SEQUENCES[sequence]}", flush=True)
    print_visual_script(sequence)
    print("\nconnecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, SCREEN) as client:
        # NEVER cleared. Each step reports the slice since its own mark, so a
        # late reply lands in a later step instead of being destroyed.
        acks: list[tuple[float, str]] = []
        unsubscribe = client.add_response_listener(lambda ack: acks.append((time.perf_counter(), repr(ack))))
        # counts[half][jump label] -- what the verdict table is built from.
        counts: dict[str, dict[str, int]] = {"armed": {}, "control": {}}

        async def send_and_count(label: str, coro) -> int:
            """Send, settle, report the slice since the mark, return its size."""
            mark = len(acks)
            sent_at = time.perf_counter()
            try:
                await coro
            except Exception as ex:
                print(f"    {label}: SEND FAILED: {ex!r} (continuing)", flush=True)
            await asyncio.sleep(SETTLE_SECONDS)
            window = acks[mark:]
            if window:
                print(f"    {label}: {len(window)} ack(s)", flush=True)
                for at, text in window:
                    print(f"      {at - sent_at:+.2f}s after send  {text}", flush=True)
            else:
                print(f"    {label}: *** ZERO ACKS after {SETTLE_SECONDS:.1f}s *** -- genuine "
                      f"silence, the list was not read early and is never cleared", flush=True)
            return len(window)

        async def run_jumps(half: str) -> None:
            """The three RTC jumps, identical in both halves -- that is the point."""
            for label, at, expected in JUMPS:
                target = fake_datetime(HIT_WEEKDAY, at)
                print(f"\n  {label} -> device time {target:%A %Y-%m-%d %H:%M:%S}  "
                      f"(expect on panel: {expected if half == 'armed' else 'clock face'})",
                      flush=True)
                counts[half][label] = await send_and_count(f"set_time [{half}]",
                                                           client.device.set_time(target))
                await asyncio.sleep(max(0.0, WATCH_SECONDS - SETTLE_SECONDS))

        gif_payload = build_theme_gif(client.screen_size.width)
        print(f"theme payload built: {len(gif_payload)}B", flush=True)

        try:
            print("\n--- baseline: the ordinary clock face (announced, not a measurement) ---",
                  flush=True)
            await send_and_count("clock baseline", client.clock.show())

            if sequence in ("full", "armed"):
                print("\n=== ARMED HALF ==========================================", flush=True)
                await send_and_count("schedule master switch ON (buzzer off -- keep it visual)",
                                     client.experimental.schedule_master_switch(enable=True, buzzer=False))
                # Put the RTC on the fabricated day BEFORE arming, so the theme
                # is armed against the same day it will be evaluated on.
                await send_and_count("set_time -> fabricated day, pre-arm (NOT one of the three "
                                     "measured jumps)",
                                     client.device.set_time(fake_datetime(HIT_WEEKDAY, clock_time(12, 0))))
                theme = make_theme(GIF_THEME_INDEX, [HIT_WEEKDAY], WINDOW_START, WINDOW_END)
                print(f"  arming theme {GIF_THEME_INDEX}: RAW week=0b{theme.week:08b} -> patched "
                      f"0b{schedule.patch_week(theme.week):08b}, window "
                      f"{WINDOW_START:%H:%M}-{WINDOW_END:%H:%M}", flush=True)
                await send_and_count("theme upload (expect StatusAck status=3 SAVED)",
                                     client.experimental.schedule_set_theme(theme, gif_payload,
                                                                           schedule.CONTENT_GIF))
                await run_jumps("armed")

            if sequence in ("full", "control"):
                print("\n=== CONTROL HALF ========================================", flush=True)
                for index in (GIF_THEME_INDEX, SPARE_THEME_INDEX):
                    dead = make_theme(index, [], clock_time(0, 0), clock_time(0, 0))
                    await send_and_count(f"disarm theme {index} (RAW week=0x00 -> patched "
                                         f"0b{schedule.patch_week(dead.week):08b}, no day bits)",
                                         client.experimental.schedule_set_theme(dead, gif_payload,
                                                                                schedule.CONTENT_GIF))
                await send_and_count("schedule master switch OFF",
                                     client.experimental.schedule_master_switch(enable=False, buzzer=False))
                await run_jumps("control")
        finally:
            # RESTORATION GUARANTEE. True time goes back FIRST, ahead of any
            # disarm or display work, so nothing that can fail runs before it.
            print("\n--- cleanup ---", flush=True)
            try:
                real_now = datetime.now()
                await client.device.set_time(real_now)
                print(f"RTC RESTORED to true local time {real_now:%A %Y-%m-%d %H:%M:%S}.", flush=True)
            except Exception as ex:
                print(f"*** RTC RESTORE FAILED: {ex!r} -- THE PANEL IS STILL ON A SPOOFED DATE."
                      f" Re-run any probe that calls common.set_time before trusting it. ***",
                      flush=True)

            for index in (GIF_THEME_INDEX, SPARE_THEME_INDEX):
                try:
                    dead = make_theme(index, [], clock_time(0, 0), clock_time(0, 0))
                    await client.experimental.schedule_set_theme(dead, gif_payload, schedule.CONTENT_GIF)
                    print(f"theme {index} disarmed.", flush=True)
                except Exception as ex:
                    print(f"theme {index} disarm FAILED: {ex!r}", flush=True)
            try:
                await client.experimental.schedule_master_switch(enable=False, buzzer=False)
                print("schedule master switch OFF.", flush=True)
            except Exception as ex:
                print(f"master switch off FAILED: {ex!r}", flush=True)
            try:
                await client.clock.show()
                print("clock restored.", flush=True)
            except Exception as ex:
                print(f"final clock.show FAILED: {ex!r}", flush=True)
            unsubscribe()

    print_verdict(counts, sequence)


def print_verdict(counts: dict[str, dict[str, int]], sequence: str) -> None:
    """The whole point of the run, on one screen."""
    print("\n=== VERDICT: set_time ack counts ============================", flush=True)
    print(f"  {'jump':24s} {'ARMED':>7s} {'CONTROL':>9s}", flush=True)
    for label, _, _ in JUMPS:
        armed = counts["armed"].get(label)
        control = counts["control"].get(label)
        print(f"  {label:24s} {('-' if armed is None else armed):>7} "
              f"{('-' if control is None else control):>9}", flush=True)
    print("  ('-' = that half was not run in this sequence)", flush=True)
    if sequence != "full":
        print("\n  Only one half ran, so there is no comparison yet -- run `full`, or the", flush=True)
        print("  other half, before recording anything.", flush=True)
        return
    armed_total = sum(counts["armed"].values())
    control_total = sum(counts["control"].values())
    print(f"\n  totals: armed {armed_total}, control {control_total}", flush=True)
    if armed_total == 0 and control_total > 0:
        print("  => REPRODUCED. An armed schedule theme silences set_time's reply. Scope", flush=True)
        print("     capabilities.py's common.ack_timing accordingly and keep the caller", flush=True)
        print("     warning on common.set_time: awaiting a reply for it can hang.", flush=True)
    elif armed_total > 0 and control_total > 0:
        print("  => NOT reproduced on this axis. P5's zero-ack runs are not explained by an", flush=True)
        print("     armed theme alone; leave P14's claim standing and look for another", flush=True)
        print("     variable (in-window vs out, master switch alone, upload proximity).", flush=True)
    elif armed_total == 0 and control_total == 0:
        print("  => BOTH halves silent. The variable is not the theme -- set_time itself is", flush=True)
        print("     silent under a condition P14 never hit. Bigger correction than expected;", flush=True)
        print("     record it loudly.", flush=True)
    else:
        print("  => armed acked and control did not: the opposite of the hypothesis. Do not", flush=True)
        print("     record a conclusion from one run; re-run `full` before writing anything.", flush=True)


asyncio.run(main(select_sequence(sys.argv[1:])))
