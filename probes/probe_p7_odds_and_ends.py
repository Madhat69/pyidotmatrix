"""P7 -- power-state semantics, the countdown/chronograph shared state machine,
and a fullscreen-color persistence recheck.

WHY THIS PROBE EXISTS
---------------------
Three loose ends from the P7 batch, each one a thing GlanceOS would otherwise
have to guess at:

1. POWER. capabilities.py says only "Power on/off exercised live" -- it does not
   say whether the device keeps ACCEPTING commands with the screen off, nor what
   turn_on puts back. A daemon that pushes frames into an off panel and gets
   acks would believe it is rendering. And if turn_on restores the previous mode
   rather than the clock, a host that assumes "power on = clock" will fight the
   firmware on every wake.

2. COUNTDOWN/CHRONOGRAPH SHARED STATE. A paused countdown was seen HIJACKING
   chronograph commands (capability sweep 2, 2026-07-20; probe_chronograph_clean
   exists purely because batch 2's chronograph run was contaminated by a paused
   countdown left over from batch 1). That was an incidental observation, never
   a map. GlanceOS renders its own timers and must never trip over device state
   the vendor app left behind, so the state machine gets mapped properly here:
   arm, pause, then walk the WHOLE chronograph command set and record what the
   panel actually does at each step.

3. FULLSCREEN-COLOR PERSISTENCE. The standing claim -- a fullscreen color
   survived ~3 days -- predates many firmware pokes and several common.reset()
   calls. This run rechecks the short end of it.

WHAT THIS PROBE DELIBERATELY DOES NOT RE-TEST
---------------------------------------------
The BRIGHTNESS FLOOR from the original P7 list. P13 settled it: the firmware
range is exactly 5-100, out-of-range values draw hard NACKs with no clamping,
and the entry is already in capabilities.py. Nothing here sends a brightness
outside that range.

WHAT ITEM 3 CAN AND CANNOT SHOW IN ONE SITTING
-----------------------------------------------
Only the DISCONNECT/RECONNECT end of persistence is testable inside one run. A
multi-day claim obviously cannot be re-established in ten minutes, and this
probe does not pretend otherwise: a clean result here means "the color survived
a BLE disconnect", nothing more. The real multi-day check is a FUTURE session's
job and needs (a) the panel power-cycled at the wall, not merely disconnected,
and (b) a look at the panel days later before any other command is sent.

This run sets that up for free. Fullscreen color is one of the two mode kinds
the firmware writes to flash (the other is effects -- the rainbow the panel
currently boots into is a leftover effect from an old lab run). So the magenta
set in phase 9 will most likely BECOME the panel's boot state. That is
deliberate: if the operator power-cycles the panel days from now and it comes up
MAGENTA, that is the multi-day persistence result, recorded without spending a
session on it.

DESIGN
------
The operator cannot see stdout -- they watch the panel. So THE PANEL LABELS ITS
OWN PHASES: each phase opens with scoreboard.show(7, phase_code) held for 3 s.
The left number is always 7 ("this is P7"), the right is the phase code 1..9;
the two sets are disjoint, so the label survives a count1/count2 orientation
surprise. The one non-label scoreboard in this run shows 99 | 99 -- far outside
the phase-code range, because it is evidence (see phase 2), not a label.

For item 2 the VISUAL result is the primary evidence; acks cannot tell a
resumed countdown from a fresh stopwatch. CONFOUND, stated up front: the
scoreboard labels between timer steps are themselves native-mode commands, and
it is conceivable that a mode switch clears the shared timer state the hijack
depends on. Against that: the original hijack survived a whole probe boundary --
a disconnect, a reconnect and a different script -- so it is clearly not fragile
to a display change. But if the hijack fails to reproduce here and everything
looks clean, the labels are suspect #1, and the follow-up is this same sequence
with no scoreboards and a stopwatch in the operator's hand.

ACK DISCIPLINE (a bug this probe exists partly to avoid repeating)
------------------------------------------------------------------
On 2026-07-25 two probes printed their ack reports in the same breath as the
send, then cleared the ack list at the phase boundary. Replies land 0.3-4.3 s
later, into an already-emptied list, so those runs reported ack SILENCE that was
purely their own impatience -- one hardware run wasted and a retraction filed.
Here: AckLog never clears, every report sleeps ACK_SETTLE first, and each ack
prints its delta from the send it is attributed to. This matters more in this
probe than in most, because "do commands still ack while the screen is off" IS
the question in phase 2 -- a false silence would be a false headline.

SAFETY
------
Nothing in the `experimental` namespace is touched; delete_device_data,
set_password, verify_password and the ae00/ae01 UART service are never used.
common.reset() (04 00 03 80) is verified non-destructive (used live 2026-07-18
to clear a stuck state) and is used twice: once for a known-state entry, and
once after the timer phases to guarantee no armed countdown is left behind.
Cleanup ends on the clock.

READOUT
-------
Phase 1 (turn_on restores what?):
  * the white/red DIY split comes back  => turn_on RESTORES the prior mode; the
    panel keeps its display state across a power-off and the host does not have
    to re-push. Note whether the frame is intact or repainted.
  * the clock comes back                => turn_on RESETS to clock; any host
    must re-send its content after every power-on.
  * the persisted rainbow effect comes back => power-off drops display state
    entirely and the panel falls back to its flash state.

Phase 2 (commands while off):
  * all three ack, and the panel shows the SCOREBOARD 99|99 on turn_on => the
    device processes commands normally with the screen off and paints an
    invisible framebuffer. Frames sent to an off panel are NOT lost, which is
    exactly the trap that makes an off panel look like a working one.
  * all three ack but the panel shows something else on turn_on => acks while
    off are receipts only; display commands are swallowed.
  * some family stops acking while off  => record WHICH; that is a per-family
    power gate and belongs in capabilities.py.

Phases 3-8 (timer state machine), the ones that matter:
  * chronograph.start (phase 5) makes the PAUSED COUNTDOWN RESUME COUNTING DOWN
    => the hijack REPRODUCES; countdown and chronograph share one device-side
    timer and the mode byte alone decides what a command means. GlanceOS must
    clear countdown state before ever touching chronograph, and vice versa.
  * chronograph.start shows a stopwatch counting UP from zero => the two are
    independent here and the 2026-07-20 observation was contamination from
    something else; the capability caveat needs softening, not hardening.
  * chronograph.reset (phase 8) leaves the COUNTDOWN visible => reset does not
    clear countdown state either, and only countdown.stop (or a reset) can.
  * any step returns to the clock => that transition is the device's own
    "timer finished/cleared" path; record which step triggered it.

Phase 9 (color persistence):
  * magenta held through the whole disconnect gap and after reconnect => the
    color survives a BLE disconnect. Says NOTHING about days; see above.
  * panel reverted during the gap => the 3-day claim is dead as stated and the
    capability entry must be rewritten from this run's evidence.

USAGE
-----
    python probes/probe_p7_odds_and_ends.py

Runtime ~6-7 minutes.

RESULT (2026-07-27): power semantics CONFIRMED; timer-state-machine and
color-persistence phases ran but their specific operator readout is not
recorded in this pass -- see below.

  * PHASE 1 (does turn_on restore the prior mode?) and PHASE 2 (do commands
    ack and take effect while the screen is off?): commands sent to a
    POWERED-OFF panel are still accepted and executed into an invisible
    framebuffer, and turn_on REVEALS whatever was last commanded while off
    rather than restoring the mode that was showing before power-off or
    resetting to the clock. This is now recorded in capabilities.py's
    common.set_power entry.
  * PHASES 3-8 (countdown/chronograph shared-state machine) and PHASE 9
    (fullscreen-colour persistence across a disconnect) were run as
    designed, but this recording pass does not have a verified, attributed
    operator readout for what each chronograph step actually did to the
    paused countdown, or whether the phase-9 magenta field survived the
    disconnect gap. Treat those two items as NOT YET CLOSED for
    documentation purposes even though the run executed -- do not infer an
    outcome from the existing chronograph/countdown caveats already in
    capabilities.py (2026-07-20), which predate this run and were not
    re-confirmed here with a citation-worthy result.
"""

import asyncio
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

PROBE_NUMBER = 7           # scoreboard count1 on every label -- "this is P7"

# Phase-2 evidence, not a label: if THIS is on the panel when the screen comes
# back on, then a scoreboard command sent to an OFF screen was executed. 99 is
# far outside the 1..9 phase-code range so it can never be misread as a label.
OFF_MARKER = 99

# Phase 9. Magenta because nothing else in this run is anywhere near it: not the
# clock's white, not the phase-1 red/blue split, and not the rainbow effect the
# panel boots into.
PERSIST_COLOR = (255, 0, 255)

LABEL_SECONDS = 3          # scoreboard hold: phase label AND phase boundary
WATCH_SECONDS = 8
LONG_WATCH_SECONDS = 12    # timer phases: long enough to see digits actually move
OFF_SECONDS = 6            # how long the screen stays off
DISCONNECT_SECONDS = 12    # phase 9's link gap
ACK_SETTLE = 2.5           # never report an ack list sooner than this after a send

_SIZE = 32                 # this probe is written for the reference 32x32


def build_split_frame() -> bytes:
    """Top half red, bottom half blue -- a frame that cannot be mistaken for
    anything else this panel produces on its own.

    Phase 1 asks whether turn_on restores the PREVIOUS mode, and that question
    is only answerable if "previous" is unmistakable. The clock, the rainbow
    effect and a solid color are all things the device can arrive at by itself;
    a two-color DIY split is not.
    """
    frame = bytearray()
    for y in range(_SIZE):
        color = b"\xff\x00\x00" if y < _SIZE // 2 else b"\x00\x00\xff"
        frame += color * _SIZE
    return bytes(frame)


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
        fresh = self._entries[self._reported:]
        self._reported = len(self._entries)
        if not fresh:
            print(f"  ACK {label}: NONE within {ACK_SETTLE:.1f}s of the send"
                  f" -- record it, silence is itself a result", flush=True)
            return
        print(f"  ACK {label}: {len(fresh)}", flush=True)
        for at, text in fresh:
            delta = at - sent_at
            note = "  <-- LATE, probably the previous send's reply" if delta > ACK_SETTLE else ""
            print(f"    send+{delta:5.2f}s  {text}{note}", flush=True)


async def label_phase(client: IDotMatrixClient, code: int, description: str) -> None:
    """Puts the phase number on the panel, because the operator has no stdout.

    Doubles as the phase boundary: the scoreboard is a native mode, so it takes
    the panel out of whatever the previous phase left running.
    """
    print(f"\n=== PHASE {code}: {description} -- scoreboard {PROBE_NUMBER} | {code}", flush=True)
    await client.scoreboard.show(PROBE_NUMBER, code)
    await asyncio.sleep(LABEL_SECONDS)


async def timed(client_call, log: AckLog, label: str) -> None:
    """Sends one command and reports its acks no sooner than ACK_SETTLE later."""
    sent_at = time.perf_counter()
    await client_call()
    await log.report(label, sent_at)


async def phase_power_restore(client: IDotMatrixClient, log: AckLog) -> None:
    """Does turn_on restore the mode that was showing, or reset to the clock?

    Nothing is sent between turn_off and turn_on, deliberately: any command in
    between would give the firmware a different answer to restore and make the
    result unreadable. Phase 2 does the with-commands version separately.
    """
    await label_phase(client, 1, "power: does turn_on restore the prior mode?")

    # A native mode (the label itself) left DIY without a disconnect, so the
    # display's cached "in DIY" flag is stale and this frame would be silently
    # swallowed. invalidate_diy_mode forces the mode-1 entry that is
    # hardware-proven to take from any panel state.
    client.display.invalidate_diy_mode()
    await client.display.show_frame(build_split_frame())
    print(f"  panel should now be RED over BLUE -- this is the state turn_on must restore"
          f" ({WATCH_SECONDS}s)", flush=True)
    await asyncio.sleep(WATCH_SECONDS)

    await timed(client.device.turn_off, log, "turn_off")
    print(f"  screen off for {OFF_SECONDS}s -- confirm it is actually dark", flush=True)
    await asyncio.sleep(OFF_SECONDS)

    await timed(client.device.turn_on, log, "turn_on")
    print(f"  WATCH ({LONG_WATCH_SECONDS}s): RED/BLUE SPLIT => turn_on restores the prior mode."
          f" CLOCK => it resets to clock. RAINBOW => it falls back to the flash state", flush=True)
    await asyncio.sleep(LONG_WATCH_SECONDS)


async def phase_commands_while_off(client: IDotMatrixClient, log: AckLog) -> None:
    """Do commands still ack with the screen off, and do they take effect?

    Three different command families go out while the panel is dark -- a common
    config command, a native mode, and a second native mode -- so a per-family
    power gate would show up as one of them going silent. The scoreboard goes
    LAST on purpose: if the device really is executing commands into an
    invisible framebuffer, then 99 | 99 is what turn_on will reveal, and that is
    a far stronger result than three acks.

    Graffiti is deliberately not in the set: it is ack-silent by design, so it
    could contribute nothing to an ack question, and it would need a DIY entry
    that would muddy the display evidence.
    """
    await label_phase(client, 2, "power: do commands ack and take effect while off?")
    await client.clock.show()
    await asyncio.sleep(3)

    await timed(client.device.turn_off, log, "turn_off")
    print("  screen off. Sending three command families into the dark ...", flush=True)

    await timed(lambda: client.device.set_brightness(60), log, "set_brightness(60) while OFF")
    await timed(client.clock.show, log, "clock.show() while OFF")
    await timed(lambda: client.scoreboard.show(OFF_MARKER, OFF_MARKER), log,
                f"scoreboard.show({OFF_MARKER}, {OFF_MARKER}) while OFF")
    print("  did the panel light up at any point during those three? (it should not)", flush=True)
    await asyncio.sleep(3)

    await timed(client.device.turn_on, log, "turn_on")
    print(f"  WATCH ({LONG_WATCH_SECONDS}s): {OFF_MARKER} | {OFF_MARKER} on the panel => commands"
          f" sent to an OFF screen ARE executed, into an invisible framebuffer."
          f" Clock or anything else => display commands were swallowed while off", flush=True)
    await asyncio.sleep(LONG_WATCH_SECONDS)


async def phase_timer_state_machine(client: IDotMatrixClient, log: AckLog) -> None:
    """Arm a countdown, pause it, then walk the whole chronograph command set.

    The visual result is the evidence: an ack cannot distinguish "resumed the
    paused countdown" from "started a fresh stopwatch". Each step gets its own
    labelled phase and a watch window long enough to see digits move, because
    the ONLY way to tell a countdown from a chronograph on this panel is which
    direction the numbers go.
    """
    steps = (
        (3, "countdown.start(5:00)", lambda: client.countdown.start(5, 0),
         "digits counting DOWN from 5:00?"),
        (4, "countdown.pause()", client.countdown.pause,
         "did the digits FREEZE? note the frozen value"),
        (5, "chronograph.start()  <-- THE HIJACK TEST", client.chronograph.start,
         "does the PAUSED COUNTDOWN RESUME counting DOWN (hijack reproduces),"
         " or does a stopwatch count UP from 0:00 (independent)?"),
        (6, "chronograph.pause()", client.chronograph.pause,
         "what froze -- the countdown or a stopwatch? note the value"),
        (7, "chronograph.resume()", client.chronograph.resume,
         "does it continue from the frozen value, restart from zero, or do nothing?"),
        (8, "chronograph.reset()", client.chronograph.reset,
         "zeroed stopwatch, the countdown still there, or back to the clock?"),
    )
    for code, name, call, question in steps:
        try:
            await label_phase(client, code, name)
            await timed(call, log, name)
            print(f"  WATCH ({LONG_WATCH_SECONDS}s): {question}", flush=True)
            await asyncio.sleep(LONG_WATCH_SECONDS)
        except Exception as ex:
            print(f"  PHASE {code} ({name}) FAILED: {ex!r}", flush=True)

    # Clear the shared timer state properly. countdown.stop() is MODE_DISABLE,
    # which was observed leaving RESUMABLE state rather than clearing (see the
    # countdown entry in capabilities.py) -- which is the whole subject of this
    # phase -- so a verified-safe common.reset() follows it. Leaving an armed
    # countdown behind is exactly the contamination that forced
    # probe_chronograph_clean.py to exist.
    print("\n  clearing timer state: countdown.stop, chronograph.reset, then device.reset", flush=True)
    for label, call in (
        ("countdown.stop", client.countdown.stop),
        ("chronograph.reset", client.chronograph.reset),
        ("device.reset", client.device.reset),
    ):
        try:
            await call()
            await asyncio.sleep(2)
        except Exception as ex:
            print(f"  cleanup {label} FAILED: {ex!r}", flush=True)
    await asyncio.sleep(4)
    try:
        await client.clock.show()
    except Exception as ex:
        print(f"  post-cleanup clock FAILED: {ex!r}", flush=True)
    print(f"  WATCH ({WATCH_SECONDS}s): is the panel a plain clock again, with no timer digits?",
          flush=True)
    await asyncio.sleep(WATCH_SECONDS)


async def phase_color_persistence(client: IDotMatrixClient, log: AckLog) -> None:
    """Set a distinctive fullscreen color and see if it survives a link gap.

    Explicit transport disconnect/reconnect rather than tearing down the context
    manager -- the client exposes both, and an explicit disconnect also disarms
    reconnect supervision so nothing races us back onto the link mid-observation.

    This is the SHORT end of the persistence question only. The multi-day claim
    needs a power-cycle and a future session; see the module docstring.
    """
    await label_phase(client, 9, "fullscreen color persistence across a link gap")
    await timed(lambda: client.color.show(PERSIST_COLOR), log, f"color.show{PERSIST_COLOR}")
    print(f"  panel should be solid MAGENTA ({WATCH_SECONDS}s)", flush=True)
    await asyncio.sleep(WATCH_SECONDS)

    print(f"  disconnecting for {DISCONNECT_SECONDS}s -- WATCH THE PANEL THROUGH THE WHOLE GAP."
          f" Does it stay magenta, or revert (and after how long)?", flush=True)
    await client.disconnect()
    await asyncio.sleep(DISCONNECT_SECONDS)
    await client.connect()
    print(f"  reconnected (is_connected={client.is_connected}). WATCH ({WATCH_SECONDS}s):"
          f" still magenta => the color survived the disconnect."
          f" Note that the reconnect ITSELF sends nothing that would repaint it", flush=True)
    await asyncio.sleep(WATCH_SECONDS)
    print("  NOTE FOR THE FUTURE: magenta is now most likely the panel's flash/boot state."
          " If a power-cycle days from now comes up MAGENTA, that is the multi-day result;"
          " if it comes up rainbow, the 3-day claim is stale.", flush=True)


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        log = AckLog()
        unsubscribe = client.add_response_listener(log.record)

        # Known-state entry: reset (04 00 03 80, verified non-destructive),
        # settle, clock baseline -- this run's timer phases are only readable
        # from a device with no timer state pending. Nothing experimental used.
        try:
            print("resetting device to a known state ...", flush=True)
            await client.device.reset()
            await asyncio.sleep(4)
            await client.clock.show()
            await asyncio.sleep(3)
            print("baseline: clock.", flush=True)
        except Exception as ex:
            print(f"  reset/clock baseline FAILED: {ex!r}", flush=True)

        # Each phase is guarded so one failure cannot end the run. The color
        # phase runs LAST so that the magenta it writes is the final flash state
        # (the timer cleanup's common.reset would otherwise land on top of it).
        for name, phase in (
            ("power restore", phase_power_restore),
            ("commands while off", phase_commands_while_off),
            ("timer state machine", phase_timer_state_machine),
            ("color persistence", phase_color_persistence),
        ):
            try:
                await phase(client, log)
            except Exception as ex:
                print(f"\n*** {name} FAILED: {ex!r} -- continuing ***", flush=True)

        print("\nverdict to record:", flush=True)
        print("  turn_on restored: PRIOR MODE / CLOCK / FLASH STATE (rainbow).", flush=True)
        print("  while off: which families acked, and did 99|99 appear on turn_on?", flush=True)
        print("  chronograph.start onto a paused countdown: HIJACK (counts down) or"
              " INDEPENDENT (counts up)?", flush=True)
        print("  which command finally cleared the timer state.", flush=True)
        print("  magenta across the disconnect: SURVIVED / REVERTED (and when).", flush=True)

        unsubscribe()
        try:
            await client.device.set_brightness(100)
            await client.clock.show()
            print("clock restored. done.", flush=True)
        except Exception as ex:
            print(f"*** RESTORE FAILED: {ex!r} -- CHECK THE PANEL BY HAND ***", flush=True)


asyncio.run(main())
