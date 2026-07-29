"""P17 -- does brightness apply immediately in every mode, and what does eco do?

WHY THIS PROBE EXISTS
---------------------
Brightness is the most universal user-facing control on the panel and the one a
daemon touches on every scene, yet its cross-mode semantics are INFERRED rather
than established. capabilities.py records only "5-100% works; out-of-range
values nacked by the device via fa03" (common.set_brightness, VERIFIED) -- which
says the command is ACCEPTED, not that pixels change while a GIF is playing.
"Acks confirm receipt, not effect" is this lab's most expensive repeated lesson
(native text acked SAVED for days before anyone proved it rendered), so an
ack-only brightness claim is precisely the sort of thing that fails in the field
and is blamed on something else.

Eco is worse: the eco entry in capabilities.py rests on probe_capability_sweep3
(2026-07-21), which set eco_brightness=5 with the window covering now, saw the
panel dim, disabled eco, and saw brightness come back. That run NEVER SET A
BRIGHTNESS FIRST, so "disable restored brightness" cannot distinguish
"restores the value the host last set" from "resets to a firmware default that
happened to look the same". This probe pins a known prior value (100) before eco
ever runs, which makes those two outcomes visibly different.

WHAT THIS PROBE DELIBERATELY DOES NOT RE-TEST
---------------------------------------------
The brightness BOUNDARY. P13 established the firmware-valid range is exactly
5-100, with hard NACKs outside it and no clamping, and the SDK's
validate_brightness raises before such a value can reach the wire anyway. Every
value sent here is inside 5..100 on purpose.

DESIGN
------
The operator cannot see stdout -- they watch the panel. So THE PANEL LABELS ITS
OWN PHASES: each phase opens with scoreboard.show(17, phase_code) held for 3 s.
The left number is always 17 ("this is P17"); the right number is the phase code
1..9. The two sets are disjoint, so the label reads correctly even if count1 and
count2 render in the opposite orientation to what we expect: a 17 can only be
the probe number, a single digit can only be the phase.

Part A discriminates the three possible brightness semantics per mode with a
fixed four-step choreography inside each mode:

    set 100 -> enter mode -> step 40 -> step 5 -> RE-ISSUE THE MODE COMMAND -> 100

  * dims at the step               => brightness applies IMMEDIATELY in this mode.
  * unchanged at the step, dims on the re-issue => brightness needs a REDRAW.
  * unchanged throughout, and only the next mode looks different => IGNORED
    until the mode changes.

The re-issue is the whole point of the middle step and is cheap in every mode:
a fresh full frame for DIY, gif.activate_stored (the ~1 s CRC-recognition
takeover, no re-upload) for GIF, effect.show again for effect, clock.show again
for clock.

ACK DISCIPLINE (a bug this probe exists partly to avoid repeating)
------------------------------------------------------------------
On 2026-07-25 two probes printed their ack reports in the same breath as the
send, then cleared the ack list at the phase boundary. The device's replies
land 0.3-4.3 s later, into an already-emptied list, so those runs reported ack
SILENCE that was purely their own impatience -- one whole hardware run wasted
and a retraction filed. Here: AckLog never clears anything, every report sleeps
ACK_SETTLE seconds before reading, and each ack prints its delta from the send
it is attributed to. An ack that still arrives late shows up in the NEXT report
with a delta large enough to place it correctly.

SAFETY / RESTORATION
--------------------
Nothing in the `experimental` namespace is touched; delete_device_data,
set_password, verify_password and the ae00/ae01 UART service are never used.
common.reset() (04 00 03 80) is the only reset here and is verified
non-destructive (used live 2026-07-18 to clear a stuck state).

ECO IS RESTORED TO A DISABLED, HARMLESS CONFIGURATION IN A `finally` BLOCK, so
it runs even if a phase raises: eco.set_mode(False, 22, 0, 6, 0,
eco_brightness=100) -- disabled, an ordinary night window, and an eco brightness
of 100 so that even if some firmware path re-enabled it, it could not dim
anything. Brightness is put back to 100 and the clock restored. Leaving a live
eco window behind would dim the operator's desk display for hours, which is why
this is a `finally` and not the last line of the happy path.

Eco is time-window driven, so the ACTIVE window is built around datetime.now()
rather than hardcoded -- a hardcoded window would simply never fire. If the run
starts within ~20 minutes of midnight the window wraps to the next day; the
probe warns rather than silently producing a meaningless result.

READOUT
-------
Part A, per mode:
  * dims/brightens at the moment of each step  => IMMEDIATE. Document brightness
    as mode-independent and the daemon can set it whenever it likes.
  * no change at the step but the re-issue applies it => REDRAW-GATED in that
    mode. The daemon must re-push the current content after any brightness
    change, or users will see the setting "not work" until the scene changes.
  * no change at all inside the mode => IGNORED in that mode; brightness becomes
    a mode-entry parameter and the capability entry needs a per-mode caveat.
  * ack present but no visual change anywhere => another "acked, no effect"
    member of the freeze_screen / set_speed family; say so loudly.

Part B:
  * eco ON dims, eco OFF returns the panel to the 100 we set  => eco SAVES AND
    RESTORES the host's brightness. capabilities.py's claim stands, now on
    evidence that could have falsified it.
  * eco OFF leaves the panel at the eco level                 => the eco value
    STICKS; every caller must re-send brightness after leaving eco, and the
    current capability wording is wrong.
  * set_brightness DURING eco brightens the panel  => host writes WIN over eco;
    eco is a one-shot dim, not a clamp.
  * set_brightness DURING eco does nothing (or is undone)     => eco CLAMPS.
    GlanceOS must know eco is active before trusting any brightness write.
  * panel is still dim after disconnect/reconnect  => the eco CONFIG lives on
    the device and runs autonomously; it is device state a fresh client inherits
    and cannot see. That is a documentation-critical result.
  * panel comes back bright after reconnect        => eco is session state only.
  * turn_off/turn_on inside an eco window comes back DIM  => power and eco are
    independent; eco re-applies on wake.
  * comes back BRIGHT => turn_on resets brightness, which would let a daemon
    silently defeat a user's eco setting.

USAGE
-----
    python probes/probe_p17_brightness_eco.py

Runtime ~6-8 minutes. Watch the panel the whole way; the scoreboard labels tell
you which phase you are in.

RESULT (2026-07-27): CLOSED.

Part A -- brightness applies IMMEDIATELY and PERSISTS in every mode tested
(DIY frame, GIF, effect, clock): the step-down and step-up brightness
changes took effect the moment the command landed in every phase, never
gated on a redraw, and stayed in force until the next brightness command,
across mode re-entries. Operator: "the panel is 100%, the picture draws and
then changes to 40%. If you then leave it there, the panel will stay there.
Until you send another brightness command."

Part B -- eco: eco_brightness applies live, is a one-shot dim rather than a
clamp (a host set_brightness(100) sent into an active eco window won
outright), and its configuration is autonomous device state that survived a
disconnect with no host attached. See capabilities.py's eco.set_mode entry
for the full account, which also folds in probe_p17b_eco_isolation.py's
lux-instrumented numbers for the eco-restores-brightness claim this part was
designed to test with a known prior value pinned first.
"""

import asyncio
import io
import time
from datetime import datetime, timedelta

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"

PROBE_NUMBER = 17          # scoreboard count1 on every label -- "this is P17"

# Every brightness sent here is inside the firmware-valid 5..100 (P13). The
# ladder is deliberately coarse: 100 -> 40 -> 5 is unmistakable to the eye, and
# a subtle step would make "no change" indistinguishable from "small change".
BRIGHT = 100
MID = 40
DIM = 5

LABEL_SECONDS = 3          # scoreboard hold: phase label AND phase boundary
SETTLE_SECONDS = 3         # after entering a mode, before touching brightness
WATCH_SECONDS = 6          # after each brightness step
ECO_WATCH_SECONDS = 9      # eco changes may not be instant; give them room
ACK_SETTLE = 2.5           # never report an ack list sooner than this after a send

# Effect phase content. Style 0 with three saturated colors at the default
# speed -- the point is that SOMETHING animated and colorful is on the panel,
# not which effect it is.
EFFECT_STYLE = 0
EFFECT_COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]

_SIZE = 32                 # this probe is written for the reference 32x32


def build_diy_frame() -> bytes:
    """A white field with a black cross: unmistakably OUR frame.

    White because a large white area makes a brightness change maximally
    visible; the cross because a plain white panel would be indistinguishable
    from a fullscreen-color command, and this phase must prove that a DIY FRAME
    is what is on screen when brightness moves.
    """
    frame = bytearray([255] * (_SIZE * _SIZE * 3))
    for i in range(_SIZE):
        for x, y in ((i, _SIZE // 2), (_SIZE // 2, i)):
            offset = (y * _SIZE + x) * 3
            frame[offset:offset + 3] = b"\x00\x00\x00"
    return bytes(frame)


def build_probe_gif() -> bytes:
    """An 8-frame white bar sweeping across black.

    White for the same brightness-visibility reason as the DIY frame, and
    MOVING so the operator can tell native GIF playback from a static frame at a
    glance. Small (8 frames) to keep the one upload in this run short.
    """
    frames = []
    for step in range(8):
        im = Image.new("RGB", (_SIZE, _SIZE), (0, 0, 0))
        px = im.load()
        for x in range(step * 4, step * 4 + 4):
            for y in range(_SIZE):
                px[x, y] = (255, 255, 255)
        frames.append(im)
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=150, loop=0)
    return buf.getvalue()


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
    the panel out of whatever the previous phase left running and each phase
    enters its mode fresh.
    """
    print(f"\n=== PHASE {code}: {description} -- scoreboard {PROBE_NUMBER} | {code}", flush=True)
    await client.scoreboard.show(PROBE_NUMBER, code)
    await asyncio.sleep(LABEL_SECONDS)


async def step_brightness(client: IDotMatrixClient, log: AckLog, percent: int, note: str) -> None:
    sent_at = time.perf_counter()
    await client.device.set_brightness(percent)
    await log.report(f"set_brightness({percent})", sent_at)
    print(f"  WATCH ({WATCH_SECONDS}s): {note}", flush=True)
    await asyncio.sleep(WATCH_SECONDS)


async def run_mode_phase(
    client: IDotMatrixClient,
    log: AckLog,
    code: int,
    name: str,
    enter,          # awaitable factory: puts the mode on the panel
    reissue,        # awaitable factory: re-sends the SAME mode, the redraw probe
) -> None:
    """The identical four-step choreography for one display mode.

    Brightness is set to BRIGHT *before* the mode is entered so the mode renders
    at a known level; every later observation is then a change from that.
    """
    await label_phase(client, code, f"brightness inside {name}")

    await client.device.set_brightness(BRIGHT)
    await asyncio.sleep(1)

    sent_at = time.perf_counter()
    await enter()
    await log.report(f"enter {name}", sent_at)
    print(f"  {name} should be on the panel now at brightness {BRIGHT} ({SETTLE_SECONDS}s)", flush=True)
    await asyncio.sleep(SETTLE_SECONDS)

    await step_brightness(client, log, MID, f"did {name} dim to ~{MID}% AT THE MOMENT of the command?")
    await step_brightness(client, log, DIM, f"did {name} dim further to {DIM}% immediately?")

    # The discriminator: brightness is already DIM, and this re-sends the SAME
    # mode command. If the panel only dims NOW, brightness is redraw-gated here.
    sent_at = time.perf_counter()
    await reissue()
    await log.report(f"re-issue {name} at brightness {DIM}", sent_at)
    print(f"  WATCH ({WATCH_SECONDS}s): the mode was just RE-SENT with brightness still {DIM}."
          f" If the panel dims only NOW, brightness in {name} is REDRAW-GATED", flush=True)
    await asyncio.sleep(WATCH_SECONDS)

    await step_brightness(client, log, BRIGHT, f"did {name} return to full brightness immediately?")


async def part_a(client: IDotMatrixClient, log: AckLog) -> None:
    """Brightness while DIY, GIF, effect and clock are each actively displayed."""
    gif_bytes = build_probe_gif()
    diy_frame = build_diy_frame()

    # One upload, up front: the GIF phase then re-enters via activate_stored,
    # the ~1 s CRC-recognition takeover, so the phase choreography stays the
    # same shape (and the same length) as the other three.
    try:
        print("\nuploading the probe GIF once (later phases reuse it via activate_stored) ...", flush=True)
        sent_at = time.perf_counter()
        await client.gif.upload_bytes(gif_bytes)
        await log.report("gif upload", sent_at)
    except Exception as ex:
        print(f"  GIF upload FAILED: {ex!r} -- the GIF phase will still try activate_stored", flush=True)

    async def enter_diy() -> None:
        # Any native mode (the scoreboard label, for one) leaves DIY without a
        # disconnect, so the display's cached "in DIY" flag goes stale and the
        # frame would be silently swallowed. invalidate_diy_mode forces the
        # mode-1 entry that is hardware-proven to take from any panel state.
        client.display.invalidate_diy_mode()
        await client.display.show_frame(diy_frame)

    async def enter_gif() -> None:
        recognized = await client.gif.activate_stored(gif_bytes)
        if not recognized:
            print("  activate_stored did NOT recognize the bytes (device holds a different gif);"
                  " re-uploading", flush=True)
            await client.gif.upload_bytes(gif_bytes)

    async def enter_effect() -> None:
        await client.effect.show(EFFECT_STYLE, EFFECT_COLORS)

    async def enter_clock() -> None:
        await client.clock.show()

    phases = (
        (1, "DIY frame (white field, black cross)", enter_diy, enter_diy),
        (2, "GIF (white bar sweeping)", enter_gif, enter_gif),
        (3, "effect (3-color, style 0)", enter_effect, enter_effect),
        (4, "clock", enter_clock, enter_clock),
    )
    for code, name, enter, reissue in phases:
        try:
            await run_mode_phase(client, log, code, name, enter, reissue)
        except Exception as ex:
            print(f"  PHASE {code} ({name}) FAILED: {ex!r}", flush=True)


async def part_b(client: IDotMatrixClient, log: AckLog) -> None:
    """Eco: restore semantics, host-write precedence, reconnect and power."""
    now = datetime.now()
    start = now - timedelta(minutes=2)
    end = now + timedelta(minutes=20)
    if end.date() != start.date():
        print("\n*** WARNING: the eco window wraps midnight (start hour > end hour)."
              " The firmware may treat that as an empty window and never dim."
              " If Part B shows no dimming at all, re-run away from midnight before"
              " concluding anything. ***", flush=True)
    window = (start.hour, start.minute, end.hour, end.minute)
    print(f"\neco window for this run: {start:%H:%M} -> {end:%H:%M} (now {now:%H:%M})", flush=True)

    # Phase 5: a KNOWN prior brightness. This is what makes "eco restored the
    # brightness" a falsifiable statement rather than sweep3's ambiguity.
    await label_phase(client, 5, "clock at a KNOWN brightness (100), pre-eco baseline")
    await client.clock.show()
    await client.device.set_brightness(BRIGHT)
    print(f"  panel should be clock at {BRIGHT}% ({ECO_WATCH_SECONDS}s) -- this is the value eco"
          f" must restore later", flush=True)
    await asyncio.sleep(ECO_WATCH_SECONDS)

    # Phase 6: eco ON with the window covering now.
    await label_phase(client, 6, "eco ON, window covers now, eco brightness 5")
    await client.clock.show()
    sent_at = time.perf_counter()
    await client.eco.set_mode(True, *window, eco_brightness=DIM)
    await log.report("eco ON", sent_at)
    print(f"  WATCH ({ECO_WATCH_SECONDS}s): did the panel dim, and how long did it take?", flush=True)
    await asyncio.sleep(ECO_WATCH_SECONDS)

    # Phase 7: eco OFF -- back to 100 (restores the host's value) or stuck at 5?
    await label_phase(client, 7, "eco OFF -- does brightness return to the 100 we set?")
    await client.clock.show()
    sent_at = time.perf_counter()
    await client.eco.set_mode(False, *window, eco_brightness=DIM)
    await log.report("eco OFF", sent_at)
    print(f"  WATCH ({ECO_WATCH_SECONDS}s): FULL brightness => eco restored the host's {BRIGHT}."
          f" Still dim => the eco value STICKS and every caller must re-send brightness", flush=True)
    await asyncio.sleep(ECO_WATCH_SECONDS)

    # Phase 8: does a host brightness write win against an ACTIVE eco window?
    await label_phase(client, 8, "eco ON again, then set_brightness(100) during eco")
    await client.clock.show()
    await client.eco.set_mode(True, *window, eco_brightness=DIM)
    await asyncio.sleep(ECO_WATCH_SECONDS)
    print("  eco should be dimming the panel now; sending set_brightness(100) INTO the eco window",
          flush=True)
    sent_at = time.perf_counter()
    await client.device.set_brightness(BRIGHT)
    await log.report("set_brightness(100) during eco", sent_at)
    print(f"  WATCH ({ECO_WATCH_SECONDS}s): bright => host writes WIN, eco is a one-shot dim."
          f" Still dim (or dims again) => eco CLAMPS", flush=True)
    await asyncio.sleep(ECO_WATCH_SECONDS)

    # Phase 9: does the eco configuration survive a BLE disconnect/reconnect?
    # Explicit transport disconnect/connect rather than tearing down the context
    # manager -- the client exposes both, and an explicit disconnect also
    # disarms reconnect supervision so nothing races us back onto the link.
    await label_phase(client, 9, "eco survives disconnect/reconnect?")
    await client.clock.show()
    await asyncio.sleep(2)
    print("  disconnecting for 12s -- WATCH THE PANEL THROUGH THE WHOLE GAP:"
          " does it stay dim, dim later on its own, or go bright?", flush=True)
    await client.disconnect()
    await asyncio.sleep(12)
    await client.connect()
    print(f"  reconnected (is_connected={client.is_connected}). WATCH ({ECO_WATCH_SECONDS}s):"
          f" dim now => the eco CONFIG lives on the device and runs without a host", flush=True)
    await asyncio.sleep(ECO_WATCH_SECONDS)

    # Still inside the eco window: what does the screen power state do with it?
    print("\n  eco + power: turning the screen OFF for 5s, then back ON", flush=True)
    sent_at = time.perf_counter()
    await client.device.turn_off()
    await log.report("turn_off during eco", sent_at)
    await asyncio.sleep(5)
    sent_at = time.perf_counter()
    await client.device.turn_on()
    await log.report("turn_on during eco", sent_at)
    print(f"  WATCH ({ECO_WATCH_SECONDS}s): back DIM => eco re-applies on wake."
          f" Back BRIGHT => turn_on defeats an active eco window", flush=True)
    await asyncio.sleep(ECO_WATCH_SECONDS)


async def restore(client: IDotMatrixClient) -> None:
    """Leaves the panel in a state the operator can live with for the rest of the day.

    Disabled eco, an ordinary 22:00-06:00 window, and eco_brightness=100 -- so
    even if some firmware path re-enabled the window on its own, it could not
    dim anything. Then full brightness and the clock. Each step is guarded
    separately: a failure to restore eco must not also cost us the clock.
    """
    for label, action in (
        ("eco disabled (window 22:00-06:00, eco brightness 100 -- inert either way)",
         lambda: client.eco.set_mode(False, 22, 0, 6, 0, eco_brightness=100)),
        (f"brightness {BRIGHT}", lambda: client.device.set_brightness(BRIGHT)),
        ("clock", lambda: client.clock.show()),
    ):
        try:
            await action()
            print(f"restored: {label}", flush=True)
        except Exception as ex:
            print(f"*** RESTORE FAILED ({label}): {ex!r} -- CHECK THE PANEL BY HAND ***", flush=True)


async def main() -> None:
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        log = AckLog()
        unsubscribe = client.add_response_listener(log.record)
        try:
            # Known-state entry: reset (04 00 03 80, verified non-destructive),
            # settle, clock baseline. Nothing experimental is touched.
            try:
                print("resetting device to a known state ...", flush=True)
                await client.device.reset()
                await asyncio.sleep(4)
                await client.clock.show()
                await asyncio.sleep(3)
                print("baseline: clock.", flush=True)
            except Exception as ex:
                print(f"  reset/clock baseline FAILED: {ex!r}", flush=True)

            await part_a(client, log)
            await part_b(client, log)

            print("\nverdict to record:", flush=True)
            print("  per mode (DIY/GIF/effect/clock): IMMEDIATE / REDRAW-GATED / IGNORED.", flush=True)
            print("  eco OFF -> 100 = eco restores the host's brightness;"
                  " -> still dim = the eco value sticks.", flush=True)
            print("  brightness write during eco: WINS (one-shot dim) or LOSES (eco clamps).", flush=True)
            print("  dim through the disconnect gap = eco config is autonomous device state.", flush=True)
            print("  after turn_on inside the window: DIM = eco re-applies; BRIGHT = power defeats eco.",
                  flush=True)
        finally:
            # Restoration runs even if a phase raised: an eco window left armed
            # would keep dimming the operator's desk display for the next 20
            # minutes, and a half-run probe must not cost them that.
            unsubscribe()
            await restore(client)
            print("done.", flush=True)


asyncio.run(main())
