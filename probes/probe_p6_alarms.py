"""P6 -- Multi-slot alarm groundwork for GlanceOS M7 Stage 4.

WHY THIS PROBE EXISTS
---------------------
Everything we know about Timer alarms was learned from ONE slot. timer_set is
VERIFIED (chunked upload, GIF + PNG content, buzzer, week mask), but GlanceOS
M7 Stage 4 wants to offer several alarms at once, and the multi-slot behavior is
entirely unmapped. Four questions gate that feature:

  Q1  Do two armed slots BOTH fire, and in what order?
  Q2  What happens when one slot's fire window overlaps another slot's start?
  Q3  Does timer_close on slot 0 leave slot 1 armed, or is it a global disarm?
      This matters more than it looks: capabilities.py rates timer_close only
      SOURCE_DERIVED because its ack is a STATE ECHO, not an accept/reject
      (statuses 0/1/3 observed from different states), so "the close was acked"
      has never meant "the slot was disarmed".
  Q4  Do armed slots survive a device POWER-CYCLE?

Q4 cannot be driven from here -- it needs someone to pull the power. The run is
therefore SPLIT (see USAGE): `arm` leaves two slots armed and exits, the
operator physically power-cycles the panel, `check` reconnects and reports what
survived.

METHOD -- RTC SPOOFING
----------------------
No phase waits for a real clock minute. common.set_time owns the device RTC and
alarms are evaluated against it -- hardware-proven 2026-07-21
(probes/probe_timer_weekbit.py), where spoofing the date flipped a day-masked
alarm from firing to silent. Every device time here is derived from ONE offset
(spoofed base minus real now) rather than by re-reading the clock, so the
seconds an upload spends on the BLE link never desynchronize the arithmetic.

The week mask is ALL SEVEN DAYS in every phase (build_timer_week(range(7))).
Timer's day map is already hardware-verified, and pinning every day removes the
weekday as a variable: nothing in this probe can fail for a day-mask reason, and
`check` works no matter which day the operator gets round to running it.

DURATION: timer.DURATION_10S is bucket 0 = 10 seconds (protocol/timer.py's
DURATION_SECONDS), the shortest bucket the firmware offers, used everywhere
except Q2 -- which NEEDS a long window to create the overlap and so uses
DURATION_60S (bucket 2 = 60 s).

WHAT THE OPERATOR SEES
----------------------
The operator watches the panel, not stdout. Each phase opens with a scoreboard
label held 4 s -- count1 = PHASE NUMBER, count2 = HOW MANY FIRES TO EXPECT --
then the panel returns to the clock as a neutral baseline. The two slots are
made deliberately unmistakable, so "which one fired" needs no timing skill:

    SLOT 0  -- full-panel RED <-> BLACK flash, WITH THE BUZZER.
    SLOT 1  -- full-panel BLUE <-> BLACK flash, SILENT.

Exactly one of the two beeps, so the buzzer is an unambiguous anchor for
ordering: "beep-then-blue" and "blue-then-beep" are different answers to Q1.

FIRE RITUAL: at fire time the panel shows the CLOCK for a second or two before
the alarm's content takes over -- hardware-confirmed 2026-07-12, expected, not a
bug. A brief clock flash between two fires is therefore not evidence of
anything; only the coloured content counts as a fire.

CRITICAL -- THE ACK BUG THIS PROBE DOES NOT REPRODUCE
-----------------------------------------------------
The 2026-07-26 night run reported ack silence for a whole class of frames and
that finding had to be RETRACTED: it read the ack list immediately after the
send, before the device's reply (~0.3-4.3 s later) arrived, then cleared the
list at the phase boundary. Here every send is timestamped, followed by a
mandatory ACK_SETTLE_SECONDS (2.0 s) wait BEFORE the list is read, the list is
cleared only AFTER printing, and each ack carries its send->ack DELTA. This
matters more here than in most probes: timer_close's status echo (1 = empty /
unsaved slot, 3 = a slot with content saved) is the ONLY arm-state readback the
device offers, so cleanup deliberately prints it per slot as a second,
independent answer to Q3 and Q4.

MANDATORY -- CLOCK RESTORATION GUARANTEE
----------------------------------------
This probe spoofs the device RTC to fabricated FUTURE dates. Every mode restores
the true current time in a `finally` block that runs on EVERY exit path --
exception, phase failure, or KeyboardInterrupt -- and the restore is the FIRST
statement of that block, ahead of any disarm or display work, so nothing that
can fail runs before it. A panel left on a spoofed date fires alarms at wrong
wall-clock times and corrupts every later observation.

DISARM POLICY, AND THE ONE DELIBERATE EXCEPTION
-----------------------------------------------
`default` and `check` close BOTH slots before exiting, unconditionally.

`arm` DOES NOT, and must not: leaving the slots armed across the power-cycle IS
the experiment. That is the one intentional deviation from "disarm before
exiting" in this probe, it is announced at runtime, and `check` closes both
slots whether or not it saw them fire -- so the pair of runs still ends with a
clean device. If the operator arms and then abandons the run, the slots stay
armed at 12:34 / 12:35 device-time on EVERY day until something closes them;
running `check` (or any later probe's cleanup) clears them.

SAFETY
------
The three absolute exclusions are honoured: no set_password / verify_password
(lockout risk, no known factory reset), no write to the ae00/ae01 UART service
(OTA-adjacent surface on a Telink SoC, brick risk), and no
experimental.delete_device_data (destructive, irreversible, never
hardware-verified). common.reset() (04 00 03 80) is the verified-safe
known-state entry -- and it is deliberately NOT sent in `check` mode, where
resetting the device would destroy the very persistence being measured.

The rest of client.experimental IS exercised here, deliberately: timer_set and
timer_close are the only alarm API that exists, and timer_close is
SOURCE_DERIVED in capabilities.py -- its bytes went to hardware once but its
disarm effect has never been confirmed. Settling that is Q3's whole purpose.

READOUT
-------
  Q1  RED+beep then BLUE, one minute apart => both slots are independent and
      fire in armed-time order. Multi-alarm is safe for GlanceOS M7.
      Only RED fires => the firmware services one slot and drops later ones;
      GlanceOS must serialize alarms itself.
      Only BLUE fires => a later arm CLOBBERS an earlier one -- slots are not
      independent storage and the whole multi-slot design is off.
      Neither fires => suspect the arming path, not the multi-slot question;
      re-run probes/probe_timer_weekbit.py before reading anything into this.
  Q2  Both slots armed for the SAME minute, slot 0 holding for 60 s and slot 1
      for 10 s, so slot 1's start falls squarely inside slot 0's window.
      RED for the full 60 s, no blue => an in-progress fire SUPPRESSES a
      colliding one. Safe, and the simplest rule to design around.
      RED interrupted by BLUE, then RED resumes / does not resume => the later
      slot PREEMPTS; note which, because "does not resume" means a collision
      silently truncates an alarm.
      BLUE only => the higher slot number wins outright.
  Q3  RED silent at 12:20 and BLUE fires at 12:21 => timer_close is PER-SLOT.
      Promote timer_close from SOURCE_DERIVED: this is the first evidence that
      it disarms anything at all, since its ack has never been a proof.
      NEITHER fires => timer_close is a GLOBAL disarm. That is a serious API
      trap and must be documented before GlanceOS ships multi-alarm.
      BOTH fire => timer_close does not disarm at all; its ack is purely a state
      echo and the capability should be marked KNOWN_BROKEN.
  Q4  (arm -> power-cycle -> check) Both fire => armed slots AND their uploaded
      content survive a power-cycle; GlanceOS can arm once and forget.
      Content-free fire (buzzer but no image) => the schedule survived but the
      payload did not; content must be re-uploaded on every boot.
      Neither fires => alarms are RAM-resident; GlanceOS must re-arm on connect.
      Cross-check with the close-ack status printed at cleanup: 3 = a slot that
      still had content saved, 1 = an empty/unsaved slot. A status of 1 with a
      fire (or 3 with no fire) is itself a finding -- record it.

USAGE
-----
    python probes/probe_p6_alarms.py            # Q1-Q3, ~10 min, no power-cycle
    python probes/probe_p6_alarms.py arm        # Q4 part 1: arm 2 slots, exit
      >>> operator now PHYSICALLY power-cycles the panel <<<
    python probes/probe_p6_alarms.py check      # Q4 part 2: what survived

`arm` and `check` are two halves of one experiment; running `check` without a
preceding `arm` measures nothing. The mode is printed at startup so a
mis-typed argument cannot be mistaken for a result.

RESULT (2026-07-27): CLOSED. All four questions answered, across the default
Q1-Q3 sequence, the isolated `q3` mode, the `arm`/`check` power-cycle pair,
and the `collide-colour`/`collide-order` follow-up modes added to break the
slot/order/colour confound.

  * Q1 -- PER-SLOT, INDEPENDENT, ORDERED. Slot 0 (red, buzzer=True) fired red
    WITH the beep at 12:02; slot 1 (blue, buzzer=False) fired blue SILENTLY
    at 12:03. Both slots fire, in armed-time order.
  * Q2 (overlapping 60s/10s windows) was exercised in the default sequence
    but no verified, attributed readout was carried forward from that phase
    this pass -- do not cite an outcome for the original 60s-vs-10s overlap
    question from this run.
  * Q3 -- PARTIAL DISARM, reproduced twice in the isolated `q3` mode from a
    fresh reset. `timer_close` clears the closed slot's CONTENT but leaves
    its SCHEDULE and BUZZER armed: closing slot 0 (armed for 12:02, red,
    buzzer) left the buzzer firing and BLUE (slot 1's content) displayed at
    12:02, not red and not silence. The identical arming sequence without
    the close produced RED at 12:02, isolating the close as the cause. This
    is a HALF-RIGHT correction of the old "does not disarm" reading, not a
    reversal of it -- timer_close does something, just not what its name
    implies. See capabilities.py's experimental.timer_close entry.
  * Q4 -- FLASH-PERSISTENT. `arm` -> physical power-cycle -> `check`: both
    slots fired again unprompted with their payloads intact (red+beep at
    12:34, blue at 12:35). GlanceOS can rely on device-side alarm storage
    across a power-cycle rather than re-arming on every reconnect.
  * Collision (new, beyond the original Q1-Q4 set): with `collide-colour`
    and `collide-order`, the HIGHER SLOT INDEX wins the display in every one
    of four index x order x colour combinations tried. Both buzzers still
    sound in a collision; the loser's content never reaches the panel at
    all rather than being overwritten -- its close-ack read status 3
    ("still had content, never consumed") against the winner's status 0
    ("fired and consumed"). Design rule for GlanceOS M7 Stage 4: put the
    alarm meant to be SEEN in the higher slot index.
  * STATE-ECHO VOCABULARY CORRECTED: this run's close-acks read 3 (had
    content) and 0 (empty/consumed) -- NOT the "3 = had content, 1 =
    empty/unsaved" pairing this probe's own comments and the 2026-07-12
    session assumed. That status-1 reading has not been reproduced and
    should not be relied on; 0, not 1, is the current best evidence for
    "empty/consumed".

capabilities.py's experimental.timer_close and experimental.timer_set entries
are updated with this run's results.
"""

import asyncio
import io
import sys
import time
from datetime import datetime, timedelta
from datetime import time as clock_time

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import timer

ADDRESS = "6D:FD:F8:A0:3E:AF"

SLOT_A = 0  # red + buzzer
SLOT_B = 1  # blue, silent

# Read the ack list only after this long. Reading it immediately after the send
# is what produced a retracted finding on 2026-07-26 -- see the docstring.
ACK_SETTLE_SECONDS = 2.0

LABEL_SECONDS = 4  # scoreboard hold: phase label AND phase boundary

# Q4's fixed device-clock minutes. `arm` and `check` are separate processes, so
# these cannot be computed -- both halves must agree on them literally.
PERSIST_A_MINUTE = clock_time(12, 34)
PERSIST_B_MINUTE = clock_time(12, 35)

MODES = ("default", "arm", "check", "q3", "collide-colour", "collide-order")


def select_mode(argv: list[str]) -> str:
    """Which half of the run this is. Deliberately not argparse -- one optional
    positional word, validated before the device is touched so a typo cannot
    half-run an experiment."""
    if not argv:
        return "default"
    if len(argv) > 1 or argv[0] not in MODES:
        print(f"usage: python probes/probe_p6_alarms.py [{' | '.join(MODES[1:])}]", flush=True)
        print("  (no argument = the full Q1-Q3 sequence, no power-cycle)", flush=True)
        raise SystemExit(2)
    return argv[0]


def fake_datetime(hour: int, minute: int, second: int = 0) -> datetime:
    """A naive local datetime on TOMORROW's date at the given wall time.

    Tomorrow, never today: a crashed run then leaves the RTC on an obviously
    wrong date rather than a plausible one. The weekday does not matter -- every
    alarm here is armed for all seven days.

    Naive on purpose: common.build_set_time converts a tz-AWARE datetime with
    .astimezone() and encodes a naive one unchanged as device-local wall time,
    which is exactly what a spoof wants.
    """
    tomorrow = datetime.now().date() + timedelta(days=1)
    return datetime.combine(tomorrow, clock_time(hour, minute, second))


def spoof_offset(base: datetime) -> timedelta:
    """The offset that makes device time read `base` right now."""
    return base - datetime.now()


def device_now(offset: timedelta) -> datetime:
    """What the device's spoofed RTC reads at this instant."""
    return datetime.now() + offset


def build_alarm_gif(size: int, color: tuple[int, int, int]) -> bytes:
    """A 2-frame COLOR <-> BLACK full-panel flash: the "this slot fired" signal.

    RGB frames left to Pillow's own palettization, the encoding hardware-
    confirmed to render at fire time (probes/probe_timer_image.py, 2026-07-12).
    An older probe hand-built P-mode frames with putpalette() and displayed
    solid black on hardware because palette index 1 fell in the black half; RGB
    frames sidestep that class of bug. optimize=True is required -- without it
    the transfer breaks (see protocol/gif.py).
    """
    frame_a = Image.new("RGB", (size, size), color)
    frame_b = Image.new("RGB", (size, size), (0, 0, 0))
    buffer = io.BytesIO()
    frame_a.save(buffer, format="GIF", save_all=True, optimize=True,
                 append_images=[frame_b], loop=0, duration=250, disposal=2)
    return buffer.getvalue()


def make_alarm(slot: int, fire_at: clock_time, duration_bucket: int, buzzer: bool) -> timer.Timer:
    """One alarm armed for EVERY weekday.

    week comes from build_timer_week rather than hand-rolled bit math: Timer's
    wire byte is bit0 = enabled, bit1..7 = Mon..Sun, and Timer -- unlike
    Schedule -- does NOT apply patch_week to it.
    """
    return timer.Timer(
        num=slot,
        week=timer.build_timer_week(range(7)),
        hour=fire_at.hour,
        minute=fire_at.minute,
        duration_bucket=duration_bucket,
        content_type=timer.CONTENT_GIF,
        buzzer_enable=buzzer,
    )


async def main(mode: str) -> None:
    print(f"MODE: {mode}", flush=True)
    if mode == "arm":
        print("  arms slots 0 and 1 and EXITS WITH THEM STILL ARMED (that is the experiment).", flush=True)
        print("  Next: physically power-cycle the panel, then run this probe with `check`.", flush=True)
    elif mode == "check":
        print("  reconnects after a power-cycle and reports what survived. No device reset is", flush=True)
        print("  sent in this mode -- resetting would destroy the thing being measured.", flush=True)
    elif mode == "q3":
        print("  Q3 ALONE, from a fresh reset. The default run's Q3 came third, after two rounds", flush=True)
        print("  of arming the same slots, so accumulated device state confounded it.", flush=True)
        print("  *** DO NOT PIPE THIS RUN THROUGH grep OR ANY FILTER. *** The timer_close state", flush=True)
        print("  echo is an ack line and is the only arm-state readback the device offers; the", flush=True)
        print("  last run's echoes were destroyed by a filtered pipe. Tee to a file instead.", flush=True)
    elif mode in ("collide-colour", "collide-order"):
        print("  Q2 follow-up: blue content has won every collision so far, but blue has always", flush=True)
        print("  been slot 1 AND the second upload -- slot index, upload order and colour are", flush=True)
        print("  confounded. These two modes break one confound each. Both slots buzz, so this", flush=True)
        print("  also answers whether two armed buzzers give one beep or two.", flush=True)
        print("  *** DO NOT PIPE THIS RUN THROUGH grep OR ANY FILTER. *** The arm and close state", flush=True)
        print("  echoes are ack lines; a filtered pipe destroyed them once already. Tee instead.", flush=True)
    else:
        print("  full Q1-Q3 sequence (~10 min). No power-cycle involved; see `arm`/`check` for Q4.", flush=True)

    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        acks: list[tuple[float, str]] = []
        unsubscribe = client.add_response_listener(lambda ack: acks.append((time.perf_counter(), repr(ack))))

        def report_acks(label: str, sent_at: float) -> None:
            """Prints every ack captured since the last report, WITH its delta.

            Never call this without an ACK_SETTLE_SECONDS wait first, and note
            the list is cleared only after printing: reading early and clearing
            at the phase boundary is the instrumentation bug that produced a
            retracted finding on 2026-07-26.
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
            await send_and_report(f"set_time -> {spoofed:%Y-%m-%d %H:%M:%S} ({note})",
                                  client.device.set_time(spoofed))

        async def label_phase(number: int, expected_fires: int, text: str) -> None:
            print(f"\n=== PHASE {number} -- scoreboard {number} | {expected_fires} -- {text}", flush=True)
            await client.scoreboard.show(number, expected_fires)
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

        async def arm(slot: int, fire_at: clock_time, bucket: int, buzzer: bool, payload: bytes) -> timer.Timer:
            alarm = make_alarm(slot, fire_at, bucket, buzzer)
            seconds = timer.DURATION_SECONDS[bucket]
            print(f"  arming slot {slot} for device-time {fire_at:%H:%M}, {seconds}s,"
                  f" buzzer={buzzer}, week=0b{alarm.week:08b} (all days)", flush=True)
            await send_and_report(f"slot {slot} upload (expect StatusAck status=3 SAVED)",
                                  client.experimental.timer_set(alarm, payload))
            return alarm

        red_gif = build_alarm_gif(client.screen_size.width, (255, 0, 0))
        blue_gif = build_alarm_gif(client.screen_size.width, (0, 80, 255))
        print(f"payloads built: red {len(red_gif)}B, blue {len(blue_gif)}B", flush=True)

        # Whatever gets armed lands here so cleanup can close it. In `arm` mode
        # this list is deliberately left unclosed -- see DISARM POLICY.
        armed: list[timer.Timer] = []

        try:
            if mode != "check":
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

            if mode == "arm":
                # --- Q4 part 1 ----------------------------------------------
                await label_phase(9, 2, "ARM for the power-cycle test -- nothing fires during this run")
                offset = spoof_offset(fake_datetime(12, 0, 0))
                await set_rtc(offset, "arm base -- restored to real time before exit")
                armed.append(await arm(SLOT_A, PERSIST_A_MINUTE, timer.DURATION_10S, True, red_gif))
                armed.append(await arm(SLOT_B, PERSIST_B_MINUTE, timer.DURATION_10S, False, blue_gif))
                print(f"\nBOTH SLOTS ARMED for device-time {PERSIST_A_MINUTE:%H:%M} /"
                      f" {PERSIST_B_MINUTE:%H:%M}, every day.", flush=True)
                print("They are left armed ON PURPOSE. Now: PHYSICALLY POWER-CYCLE THE PANEL,", flush=True)
                print("then run `python probes/probe_p6_alarms.py check`.", flush=True)

            elif mode == "check":
                # --- Q4 part 2 ----------------------------------------------
                # Slots armed for all seven days, so any date works; only the
                # wall-clock minute has to be walked up to.
                await label_phase(9, 2, "POST-POWER-CYCLE check -- EXPECT red+beep, then blue")
                offset = spoof_offset(fake_datetime(12, 33, 30))
                await set_rtc(offset, "check base -- 30s before the armed minute")
                armed.append(make_alarm(SLOT_A, PERSIST_A_MINUTE, timer.DURATION_10S, True))
                armed.append(make_alarm(SLOT_B, PERSIST_B_MINUTE, timer.DURATION_10S, False))

                print("  WATCH (~2min): RED+BUZZER at 12:34, BLUE at 12:35 => both slots AND their", flush=True)
                print("  content survived the power-cycle. A buzzer with NO image => the schedule", flush=True)
                print("  survived but the payload did not. Clock throughout => alarms are RAM-only.", flush=True)
                await sleep_until(offset, fake_datetime(12, 35, 20), "both armed minutes elapsed")

            elif mode == "q3":
                # --- Q3 in isolation -----------------------------------------
                # The reset above is this mode's whole point: nothing has armed
                # these slots since, so a fire here cannot be leftover state.
                await label_phase(3, 1, "ISOLATED Q3 -- close slot 0, leave slot 1 -- EXPECT blue ONLY")
                offset = spoof_offset(fake_datetime(12, 1, 0))
                await set_rtc(offset, "q3 base")
                closed_target = await arm(SLOT_A, clock_time(12, 2), timer.DURATION_10S, True, red_gif)
                armed.append(closed_target)
                armed.append(await arm(SLOT_B, clock_time(12, 3), timer.DURATION_10S, False, blue_gif))

                print("\n  *** STATE ECHO FOLLOWS -- DO NOT FILTER THE ACK LINES ***", flush=True)
                print("  status 3 = slot 0 HAD CONTENT SAVED, 1 = empty/unsaved.", flush=True)
                await send_and_report(f"timer_close(slot {SLOT_A}) -- STATE ECHO",
                                      client.experimental.timer_close(closed_target))

                print("  WATCH: SILENCE at 12:02 then BLUE at 12:03 => close is PER-SLOT and works.", flush=True)
                print("  RED+beep at 12:02 => close does not disarm. Nothing at either minute =>", flush=True)
                print("  close is GLOBAL.", flush=True)
                await sleep_until(offset, fake_datetime(12, 3, 40), "both armed minutes elapsed")

            elif mode == "collide-colour":
                # --- which wins a collision: slot/order, or the colour? ------
                # Payloads SWAPPED versus every previous run: slot 0 is BLUE and
                # armed first, slot 1 is RED and armed second. Same duration, so
                # neither can win on window length.
                await label_phase(4, 1, "COLLIDE/COLOUR -- slot0=BLUE first, slot1=RED second, same minute")
                offset = spoof_offset(fake_datetime(12, 1, 0))
                await set_rtc(offset, "collide-colour base")
                armed.append(await arm(SLOT_A, clock_time(12, 2), timer.DURATION_10S, True, blue_gif))
                armed.append(await arm(SLOT_B, clock_time(12, 2), timer.DURATION_10S, True, red_gif))

                print("\n  WATCH 12:02 -- both slots fire at the same minute, both buzzers armed.", flush=True)
                print("  RED displayed  => the winner is the SLOT INDEX or the UPLOAD ORDER, not", flush=True)
                print("  the colour (blue was never special). BLUE displayed => COLOUR matters.", flush=True)
                print("  AND COUNT THE BEEPS: one beep or two? Two armed buzzers have never been", flush=True)
                print("  tested together.", flush=True)
                await sleep_until(offset, fake_datetime(12, 2, 40), "the collision minute elapsed")

            elif mode == "collide-order":
                # --- slot index versus upload order --------------------------
                # Colours back to normal (slot 0 red, slot 1 blue) but the UPLOAD
                # ORDER is reversed: slot 1 first, slot 0 second. Whichever wins
                # here separates "higher slot index" from "last upload".
                await label_phase(5, 1, "COLLIDE/ORDER -- slot1=BLUE first, slot0=RED second, same minute")
                offset = spoof_offset(fake_datetime(12, 1, 0))
                await set_rtc(offset, "collide-order base")
                armed.append(await arm(SLOT_B, clock_time(12, 2), timer.DURATION_10S, True, blue_gif))
                armed.append(await arm(SLOT_A, clock_time(12, 2), timer.DURATION_10S, True, red_gif))

                print("\n  WATCH 12:02 -- both slots fire at the same minute, both buzzers armed.", flush=True)
                print("  RED (slot 0, the LATER upload) displayed  => LAST UPLOAD WINS.", flush=True)
                print("  BLUE (slot 1, the EARLIER upload) displayed => HIGHER SLOT INDEX WINS.", flush=True)
                print("  AND COUNT THE BEEPS: one beep or two?", flush=True)
                await sleep_until(offset, fake_datetime(12, 2, 40), "the collision minute elapsed")

            else:
                # --- Q1: do both fire, in what order? ------------------------
                try:
                    await label_phase(1, 2, "two slots, adjacent minutes -- EXPECT red+beep, then blue")
                    offset = spoof_offset(fake_datetime(12, 1, 0))
                    await set_rtc(offset, "Q1 base")
                    armed.append(await arm(SLOT_A, clock_time(12, 2), timer.DURATION_10S, True, red_gif))
                    armed.append(await arm(SLOT_B, clock_time(12, 3), timer.DURATION_10S, False, blue_gif))

                    print("  WATCH: RED flash + BUZZER at 12:02, then BLUE flash (silent) at 12:03.", flush=True)
                    print("  Report the ORDER and whether EACH appeared. A 1-2s clock interlude", flush=True)
                    print("  before each fire is the expected ritual, not a missed fire.", flush=True)
                    await sleep_until(offset, fake_datetime(12, 3, 40), "both fires elapsed")
                except Exception as ex:
                    print(f"  PHASE 1 FAILED: {ex!r}", flush=True)

                # --- Q2: overlapping windows ---------------------------------
                # Both slots on the SAME minute, slot 0 holding 60 s against
                # slot 1's 10 s, so slot 1's start is squarely inside slot 0's
                # window. DURATION_10S cannot produce an overlap at all -- 10 s
                # windows on adjacent minutes never touch -- so this is the one
                # phase that needs the longer bucket.
                try:
                    await label_phase(2, 9, "SAME minute, 60s vs 10s -- narrate exactly what happens")
                    offset = spoof_offset(fake_datetime(12, 9, 0))
                    await set_rtc(offset, "Q2 base")
                    armed.append(await arm(SLOT_A, clock_time(12, 10), timer.DURATION_60S, True, red_gif))
                    armed.append(await arm(SLOT_B, clock_time(12, 10), timer.DURATION_10S, False, blue_gif))

                    print("  WATCH: both armed for 12:10. Slot 0 wants the panel for 60s, slot 1 for", flush=True)
                    print("  10s. Report: red only for a full minute? red interrupted by blue? does", flush=True)
                    print("  red RESUME after blue? blue only? Note whether the buzzer sounds once.", flush=True)
                    await sleep_until(offset, fake_datetime(12, 11, 20), "slot 0's 60s window elapsed")
                except Exception as ex:
                    print(f"  PHASE 2 FAILED: {ex!r}", flush=True)

                # --- Q3: is timer_close per-slot? ----------------------------
                try:
                    await label_phase(3, 1, "close slot 0, leave slot 1 -- EXPECT blue ONLY, no beep")
                    offset = spoof_offset(fake_datetime(12, 19, 0))
                    await set_rtc(offset, "Q3 base")
                    closed_target = await arm(SLOT_A, clock_time(12, 20), timer.DURATION_10S, True, red_gif)
                    armed.append(closed_target)
                    armed.append(await arm(SLOT_B, clock_time(12, 21), timer.DURATION_10S, False, blue_gif))

                    print(f"  closing slot {SLOT_A}. Its ack is a STATE ECHO, not accept/reject:", flush=True)
                    print("  status 3 = the slot had content saved, 1 = empty/unsaved. Record it --", flush=True)
                    print("  it is the only arm-state readback the device offers.", flush=True)
                    await send_and_report(f"timer_close(slot {SLOT_A}) -- state echo",
                                          client.experimental.timer_close(closed_target))

                    print("  WATCH: SILENCE at 12:20 (slot 0 closed), BLUE at 12:21 => close is", flush=True)
                    print("  PER-SLOT. Nothing at all => close is GLOBAL. Red at 12:20 anyway =>", flush=True)
                    print("  close does not disarm and its ack means nothing.", flush=True)
                    await sleep_until(offset, fake_datetime(12, 21, 40), "both armed minutes elapsed")
                except Exception as ex:
                    print(f"  PHASE 3 FAILED: {ex!r}", flush=True)

        finally:
            # RESTORATION GUARANTEE. The true clock goes back FIRST, before any
            # disarm or display work, so nothing that can fail runs ahead of it.
            print("\n--- cleanup ---", flush=True)
            try:
                real_now = datetime.now()
                await client.device.set_time(real_now)
                print(f"RTC RESTORED to true local time {real_now:%A %Y-%m-%d %H:%M:%S}.", flush=True)
            except Exception as ex:
                print(f"*** RTC RESTORE FAILED: {ex!r} -- THE PANEL IS STILL ON A SPOOFED DATE."
                      f" Re-run any probe that calls common.set_time before trusting it. ***", flush=True)

            if mode == "arm":
                print("slots 0 and 1 LEFT ARMED on purpose (the power-cycle experiment).", flush=True)
                print("`check` closes them both; run it, or they stay armed at 12:34/12:35 daily.", flush=True)
            else:
                # One close per SLOT, not per armed object -- the phases above
                # re-arm the same two slots repeatedly.
                for slot in (SLOT_A, SLOT_B):
                    last = next((a for a in reversed(armed) if a.num == slot), None)
                    if last is None:
                        continue
                    try:
                        sent_at = time.perf_counter()
                        await client.experimental.timer_close(last)
                        await asyncio.sleep(ACK_SETTLE_SECONDS)
                        report_acks(f"timer_close(slot {slot}) at cleanup -- status 3 = had content,"
                                    f" 1 = empty/unsaved", sent_at)
                        print(f"slot {slot} closed.", flush=True)
                    except Exception as ex:
                        print(f"slot {slot} close FAILED: {ex!r}", flush=True)

            try:
                unsubscribe()
                await client.clock.show()
                print("clock restored. done.", flush=True)
            except Exception as ex:
                print(f"final clock.show FAILED: {ex!r}", flush=True)


asyncio.run(main(select_mode(sys.argv[1:])))
