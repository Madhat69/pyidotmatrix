"""P11 -- the persistence and reset matrix: what survives an interruption?

WHY THIS PROBE EXISTS
---------------------
Every reconnect story this SDK tells a caller rests on scattered, undated
observations. capabilities.py currently asserts four persistence facts, from
four different sessions, in four different vocabularies:

    clock.show                 "ticks on RTC through disconnects; not
                                flash-persisted" (2026-07-17/19)
    color.show                 "fullscreen color flash-persists across
                                power-cycle -- survived 3 days" (2026-07)
    display.diy_quit_keep_frame "survives clean disconnect but not
                                power-cycle" (2026-07-18)
    display.show_frame          DIY mode is invalidated on disconnect
                                client-side, because device-side mode state is
                                assumed lost -- an ASSUMPTION, never measured.

Nothing covers brightness, flip, text, GIF, effect, or eco at all, and no two
of the above were taken under the same interruption. PROBE_PLAN.md P11 asks for
one explicit matrix instead: every state x every interruption, each cell
recorded as PERSISTS / RESUMES / RESETS TO CLOCK / NEEDS A NEW COMMAND.

THE MATRIX THIS PROBE FILLS IN
------------------------------
Rows (states):   clock, DIY frame, fullscreen colour, GIF, text, effect,
                 flip, brightness, eco configuration.
Columns:         (1) BLE disconnect / reconnect      -- automated
                 (2) software power off / on         -- automated
                 (3) physical power-cycle at the wall -- operator, `set`/`check`

Plus `power` as its own row: does a SOFTWARE power-off survive a BLE reconnect,
and does it survive the mains?

NOT COVERED, DELIBERATELY: Timer/Schedule slots. P11 lists them, but every
route to a Timer or Schedule slot (experimental.timer_set, timer_close,
schedule_set_theme, schedule_master_switch) lives in the `experimental`
namespace, which this lab's standing exclusions forbid touching. There is no
non-experimental path to arm a slot, so the Timer/Schedule row of P11 cannot be
filled by this probe and is left explicitly open. See the OPEN ROW note in the
readout section.

Also untouched on purpose: set_password / verify_password, ae00 / ae01,
delete_device_data, and the RTC (common.set_time is never called, so no device
clock is disturbed and nothing needs restoring). graffiti is avoided entirely --
a 256-pixel graffiti command crashed this panel's BLE stack on 2026-07-25, and
the DIY-frame row exercises the full-frame path instead, which does not batch
pixels.

THE DESIGN CONSTRAINT
---------------------
One of the three interruptions -- pulling the plug -- the probe cannot perform,
and the operator who performs it CANNOT SEE STDOUT. They watch the panel. So
the physical column is split into two runs with a file handing state between
them, and every verdict is phrased as something visible on the panel rather
than something printed.

    OPERATOR WORKFLOW (physical power-cycle column)

      1. python probes/probe_p11_persistence.py set
         Establishes the state under test, writes probe_p11_state.json next to
         this file, disconnects, exits. Read what it printed BEFORE you get up.
      2. Pull the panel's power at the wall. Wait a few seconds. Plug it back
         in and let it finish booting.
      3. python probes/probe_p11_persistence.py check
         Reconnects and TOUCHES NOTHING for 30 s while you look at the panel,
         then prints the verdict vocabulary and disables eco. It does not
         restore brightness/flip/content -- run `restore` when you are done
         looking.
      4. python probes/probe_p11_persistence.py restore
         Puts the panel back to power on / unflipped / brightness 100 / eco
         off / clock.

    `set` takes an optional state name (default `combo`):

      combo       flip + brightness + DIY frame at once -- see below
      clock diy color gif text effect flip brightness eco power

    ONE PHYSICAL RUN CANNOT TEST EVERY STATE. The panel shows exactly one
    content state at a time: a GIF and a fullscreen colour cannot both be
    resident. `combo` therefore packs the three states that ARE simultaneously
    readable -- flip, brightness and the DIY frame -- into a single power-cycle,
    because the DIY frame is asymmetric enough that its orientation reports the
    flip state at the same time as its presence reports the frame state. Every
    other row needs its own set/power-cycle/check pass.

TEST CONTENT (asymmetric on purpose -- stale or mangled must not look correct)
-----------------------------------------------------------------------------
Each row owns a distinct, nameable identity so the operator can report "the
blue one survived, the text didn't" with no ambiguity:

    clock        the ordinary clock face (this row is the control)
    DIY frame    BLUE block in the TOP-LEFT quarter, CYAN block in the
                 BOTTOM-RIGHT quarter, black elsewhere, plus a small WHITE
                 square near the TOP-RIGHT corner. Rotated 180 (flip on) that
                 reads: cyan top-left, blue bottom-right, white square near the
                 BOTTOM-LEFT. No symmetry anywhere, so a flip, a mirror, or a
                 half-drawn frame is instantly visible.
    colour       flat ORANGE, whole panel. Owned by no other row.
    GIF          a small WHITE block hopping CLOCKWISE around the four corners
                 (TL -> TR -> BR -> BL) on a dim GREEN field at 4 fps -- the
                 fixture from probe_p10_interrupted_upload.py. The block's
                 corner IS the frame number, so RESTARTED-FROM-FRAME-0 and
                 CONTINUED-FROM-WHERE-IT-WAS are separable by eye. (The first
                 version of this row used a bar oscillating left<->right; the
                 2026-07-27 operator could not read its phase, which left the
                 only question the row asks unanswerable.)
    text         the word ZULU scrolling in MAGENTA.
    effect       the built-in animation in RED and BLUE only.
    flip         the clock, UPSIDE DOWN.
    brightness   flat WHITE at brightness 10 -- unmistakably dim; the reset
                 reading is the same white, glaring.
    eco          flat WHITE at brightness 100 with an eco window covering NOW
                 at eco_brightness 5 -- so the panel is DIM despite the
                 brightness being high. Distinguishable from the brightness row
                 only by what the JSON record says was set, which is why the
                 two are never armed together.
    power        the panel DARK, after a software power-off.

ACK DISCIPLINE
--------------
Tonight's earlier probes printed their ack report immediately after the send,
read an empty list because the reply had not arrived yet, then cleared the list
at the phase boundary -- manufacturing a false "zero acks" finding. This probe
always waits ACK_SETTLE_SECONDS (3.0; replies have been observed from ~0.3 s to
~4.3 s) before reading, prints the send->ack delta for every reply, and never
clears the list before it has been printed. A reply that lands even later is
not lost: it appears in the NEXT report with a negative delta and is labelled
LATE, rather than being silently dropped.

SAFETY
------
eco is the only state that could outlive the probe and dim the operator's desk
for hours. Three guards: its window ENDS 20 minutes after it is armed, so an
abandoned run self-heals; `check` disables it unconditionally after the viewing
hold; and the automated run disables it in a finally block, on the failure path
too. Brightness is restored to 100 and flip to False by the same finally, and
by the `restore` mode.

READOUT
-------
For each cell, one of four verdicts, and what each one means for the SDK:

  * PERSISTS           -- the state was still in force after the interruption.
                          The SDK may cache it and must not re-send blindly.
  * RESUMES            -- an animation was still running, from wherever it was
                          or from the start. Note which; a restart-from-zero is
                          a different device behavior than a true resume.
  * RESETS TO CLOCK    -- the panel fell back to the clock face. The SDK must
                          treat any cached display state as invalid after this
                          interruption and restore it itself.
  * NEEDS A NEW COMMAND-- the state is gone and nothing took its place (dark
                          panel, stale frame, garbage).

Specific things worth watching for:

  * DIY frame PERSISTS across a BLE reconnect => BleDisplay's unconditional
    _diy_mode_enabled invalidation on disconnect is over-cautious, and the
    reconnect path is re-entering DIY mode it did not need to.
  * DIY frame RESETS TO CLOCK across a BLE reconnect => the invalidation is
    correct and should be documented as measured, not assumed.
  * colour survives the mains but the DIY frame does not => confirms the
    2026-07 "fullscreen colour flash-persists" claim AND localizes it: the
    colour command writes flash, the frame pipeline does not.
  * brightness or flip RESETS on the mains => every caller that sets them once
    at startup is wrong; they must be re-applied on every connect.
  * eco PERSISTS across the mains => eco is stored in flash, and an SDK that
    sets an eco window is making a durable change to the user's device. That
    would need calling out in the public docs.
  * software power-off survives the mains (panel comes back DARK) => power is a
    stored setting, not a live one, and a user could be left with a black panel
    they cannot explain.
  * GIF RESUMES after a reconnect but the DIY frame does not => native modes and
    the DIY pipeline have different device-side lifetimes; the SDK's
    invalidate-on-disconnect policy should be per-mode, not global.

  * OPEN ROW: Timer/Schedule persistence is NOT measured here (standing
    exclusion on the experimental namespace). It stays open in P11.

USAGE
-----
    python probes/probe_p11_persistence.py                    # automated, all rows
    python probes/probe_p11_persistence.py gif                # automated, one row
    python probes/probe_p11_persistence.py gif diy color      # in the order given
    python probes/probe_p11_persistence.py gif gif            # the same row TWICE
    python probes/probe_p11_persistence.py --delay 120 gif    # quiet wait after the reset
    python probes/probe_p11_persistence.py --preamble ble gif    # one BLE re-init first
    python probes/probe_p11_persistence.py --preamble power gif  # one power cycle first
    python probes/probe_p11_persistence.py --no-reset gif     # no common.reset() at all
    python probes/probe_p11_persistence.py set                # arm `combo`, then exit
    python probes/probe_p11_persistence.py set gif            # arm one named state
    python probes/probe_p11_persistence.py check              # after the power-cycle
    python probes/probe_p11_persistence.py restore            # put the panel back

Row filter keys: clock, diy, color, gif, text, effect, flip, brightness, eco,
power. Repeats are KEPT and run again in place. `combo` is a set-mode row only
and is not accepted as a filter. An unrecognized key prints the accepted keys
and exits 2 before any BLE contact. The three prelude knobs -- `--delay N`,
`--preamble ble|power`, `--no-reset` -- apply to the automated mode only and
are rejected for set/check/restore. They may appear in any position.

THE RESET SHADOW
----------------
CONFIRMED 2026-07-27. Content pushed to the panel shortly after common.reset()
RENDERS CORRECTLY, ACKS NORMALLY, and IS NOT DURABLE: it vanishes at the next
disconnect or power event, with nothing in the ack stream indicating a problem.
GIF row, one fixture, one session:

    upload ~15 s after reset, quiet                  -> DIES     3 runs
    upload ~120 s after reset, QUIET (--delay 120)   -> DIES     1 run
    upload ~75-90 s after reset, AFTER an interruption -> SURVIVES 3 runs
        (the full sweep; `clock gif`; row 2 of `gif gif`)

ELAPSED TIME IS IRRELEVANT -- two minutes of silence changed nothing, while a
6 s BLE disconnect changed everything. An intervening RE-INITIALISATION is what
lifts the shadow. Note that an inert preceding row (`clock`, which changes no
mode) rescues it just as well as a mode-changing one, so it is the interruption
the row performs, not the content it sets.

This unifies three previously unrelated oddities: the isolated GIF deaths here,
P7 phase 9's magenta reverting on reconnect (set right after that phase's own
common.reset()), and probably this probe's DIY row. It matters beyond the lab:
common.reset() is the driver's remedy for a stuck panel and the daemon's
recovery paths reset and then push, so that content is guaranteed to vanish at
the first reconnect, silently.

STILL OPEN, and what each knob asks:

    --preamble ble gif    WHICH interruption lifts it? Every rescuing run so far
    --preamble power gif  performed BOTH a BLE reconnect and a power cycle, so
                          they are confounded. Either one surviving identifies a
                          sufficient event; both surviving means any re-init
                          works; NEITHER surviving means the rescuing factor is
                          something else in the preceding row and this model
                          needs revisiting.
    --no-reset gif        Was it ever about common.reset()? If content pushed on
                          a FRESH CONNECTION with no reset shows the same
                          shadow, the finding is much larger: the FIRST content
                          pushed after ANY connection is non-durable until
                          something re-initialises the device.

The preamble deliberately calls the row loop's own interrupt_ble /
interrupt_power, so a preamble interruption is byte-identical to a row's.

The full automated run takes roughly 11-13 minutes and needs no one present;
one row is about 60-75 s, so `gif gif` is about 3 minutes, `--preamble ble gif`
about 100 s and `--no-reset gif` about 85 s. Re-testing a single row used to
cost the whole run, which is why the filter exists.

RESULT (2026-07-__): pending -- NOT RUN tonight. The full persistence matrix
(clock/DIY/colour/GIF/text/effect/flip/brightness/eco x BLE reconnect/
software power/physical power-cycle) remains open. No other probe tonight
substitutes for this one -- P17/P17b establish eco's autonomous-device-state
result under a BLE disconnect specifically (recorded in capabilities.py's
eco.set_mode entry), but the rest of the P11 matrix, including every row
under a physical power-cycle, is still unmeasured.
"""

import asyncio
import io
import json
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import text as text_protocol

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

# Handoff between `set` (before the operator pulls the plug) and `check`
# (after). Lives next to the probe so the operator never retypes anything.
HANDOFF_PATH = Path(__file__).resolve().with_name("probe_p11_state.json")

# The repo's own test font; no font ships with the package itself.
FONT_PATH = Path(__file__).resolve().parent.parent / "tests" / "Rain-DRM3.otf"

# Replies have been timed from ~0.3 s (config commands) to ~4.3 s (effect).
# Anything under 1.5 s reads an empty list and invents a "no ack" finding.
ACK_SETTLE_SECONDS = 3.0

WATCH_SECONDS = 8        # operator's look at the panel after each event
BLE_GAP_SECONDS = 6      # link left down long enough to be a real disconnect
POWER_OFF_SECONDS = 5    # software off held long enough to be unambiguous
SETTLE_SECONDS = 2       # after a reconnect, before judging anything
CHECK_HOLD_SECONDS = 30  # `check` touches nothing at all for this long

NEUTRAL_BRIGHTNESS = 100  # what every restore path puts the panel back to
DIM_BRIGHTNESS = 10       # the brightness row's value: dim beyond argument
ECO_BRIGHTNESS = 5
ECO_WINDOW_MINUTES = 20   # an abandoned eco window expires on its own

BLUE = (0, 0, 220)
CYAN = (0, 200, 200)
WHITE = (255, 255, 255)
ORANGE = (255, 110, 0)
GIF_FIELD = (0, 85, 0)  # dim green field, as probe_p10_interrupted_upload uses
MAGENTA = (255, 0, 255)
EFFECT_COLORS = [(255, 0, 0), (0, 0, 255)]
EFFECT_STYLE = 0
EFFECT_SPEED = 100  # byte 5, hardware-verified as a real speed 2026-07-26
TEXT_WORD = "ZULU"
GIF_FRAME_MS = 250  # 4 fps: one corner per frame, slow enough to read the phase


# --- test content -----------------------------------------------------------

def build_diy_frame() -> bytes:
    """The DIY row's frame: asymmetric under rotation AND under mirroring.

    Blue top-left quarter, cyan bottom-right quarter, a white 3x3 square near
    the top-right corner, black everywhere else. Rotate it 180 and every
    landmark lands somewhere else, so the same picture also reports the flip
    state -- which is what lets `combo` test flip and the frame in one
    power-cycle.
    """
    w = h = SCREEN.width
    pixels = bytearray(w * h * 3)

    def put(x: int, y: int, color: tuple[int, int, int]) -> None:
        offset = (y * w + x) * 3
        pixels[offset:offset + 3] = bytes(color)

    for y in range(h):
        for x in range(w):
            if x < w // 2 and y < h // 2:
                put(x, y, BLUE)
            elif x >= w // 2 and y >= h // 2:
                put(x, y, CYAN)

    for y in range(1, 4):           # white square inset from the top-right
        for x in range(w - 4, w - 1):
            put(x, y, WHITE)
    return bytes(pixels)


def build_test_gif() -> bytes:
    """A 6x6 WHITE block hopping clockwise TL -> TR -> BR -> BL over a dim
    GREEN field -- probe_p10_interrupted_upload.build_base_gif's fixture.

    The first fixture here was a bar bouncing left<->right, and the 2026-07-27
    operator could not answer the only question this row asks: after an
    interruption, did playback RESTART at frame 0 or CONTINUE where it was? A
    fast symmetric oscillation has no readable phase. A four-corner hop does:
    the block's corner IS the frame number, so restart-versus-continue is a
    glance. Encoder settings are this probe's own (optimize=True, disposal=2 --
    protocol/gif.py requires optimize) rather than P10's, since this row already
    uploaded and rendered cleanly with them.
    """
    size = SCREEN.width
    inset, block = 2, 5  # 6x6 block, 2 px in from each edge -- P10's geometry
    far = size - inset - block - 1
    frames = []
    for x, y in ((inset, inset), (far, inset), (far, far), (inset, far)):
        frame = Image.new("RGB", (size, size), GIF_FIELD)
        ImageDraw.Draw(frame).rectangle([x, y, x + block, y + block], fill=WHITE)
        frames.append(frame)

    buffer = io.BytesIO()
    frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        optimize=True,
        append_images=frames[1:],
        loop=0,
        duration=GIF_FRAME_MS,
        disposal=2,
    )
    return buffer.getvalue()


# --- ack instrumentation ----------------------------------------------------

class AckLog:
    """Timestamped device replies, read only after the device has had time.

    The whole point of this class is the wait. Reading the list synchronously
    after a send is how the 2026-07-26 false "zero acks" finding was produced;
    `settle_and_report` is the only reader, and it always sleeps first.
    """

    def __init__(self) -> None:
        self.entries: list[tuple[float, str]] = []

    def record(self, ack: object) -> None:
        self.entries.append((time.perf_counter(), repr(ack)))

    async def settle_and_report(self, label: str, sent_at: float) -> None:
        await asyncio.sleep(ACK_SETTLE_SECONDS)
        if not self.entries:
            print(f"  acks [{label}]: *** NONE within {ACK_SETTLE_SECONDS:.1f}s *** -- record it, "
                  f"but a later reply will still show up in the next report", flush=True)
            return
        print(f"  acks [{label}]: {len(self.entries)}", flush=True)
        for at, text in self.entries:
            delta = at - sent_at
            late = "   <-- LATE: reply to an EARLIER send" if delta < 0 else ""
            print(f"    {delta:+.2f}s after send  {text}{late}", flush=True)
        self.entries.clear()  # cleared only now, after being printed


# --- state setters ----------------------------------------------------------
# Each takes the connected client and leaves exactly one row's state in force.

async def set_clock(client: IDotMatrixClient) -> None:
    await client.clock.show()


async def set_diy(client: IDotMatrixClient) -> None:
    await client.display.show_frame(build_diy_frame())


async def set_color(client: IDotMatrixClient) -> None:
    await client.color.show(ORANGE)


async def set_gif(client: IDotMatrixClient) -> None:
    await client.gif.upload_bytes(build_test_gif())


async def set_text(client: IDotMatrixClient) -> None:
    if not FONT_PATH.is_file():
        raise FileNotFoundError(f"font not found: {FONT_PATH} -- the text row cannot run without it")
    await client.text.show(
        TEXT_WORD,
        font_path=str(FONT_PATH),
        text_mode=text_protocol.MODE_MARQUEE,
        color_mode=text_protocol.COLOR_RGB,
        color=MAGENTA,
    )


async def set_effect(client: IDotMatrixClient) -> None:
    await client.effect.show(EFFECT_STYLE, EFFECT_COLORS, speed=EFFECT_SPEED)


async def set_flip(client: IDotMatrixClient) -> None:
    await client.common.set_screen_flipped(True)
    await client.clock.show()


async def set_brightness(client: IDotMatrixClient) -> None:
    await client.color.show(WHITE)
    await client.common.set_brightness(DIM_BRIGHTNESS)


async def set_eco(client: IDotMatrixClient) -> None:
    """Arms an eco window covering now, ENDING 20 minutes from now.

    The bounded end is the safety property: if the operator abandons the run
    between `set` and `check`, the panel un-dims itself rather than sitting at
    eco_brightness on someone's desk all evening.
    """
    await client.color.show(WHITE)
    await client.common.set_brightness(NEUTRAL_BRIGHTNESS)
    start = datetime.now() - timedelta(minutes=2)
    end = start + timedelta(minutes=ECO_WINDOW_MINUTES + 2)
    await client.eco.set_mode(
        enabled=True,
        start_hour=start.hour, start_minute=start.minute,
        end_hour=end.hour, end_minute=end.minute,
        eco_brightness=ECO_BRIGHTNESS,
    )


async def set_power(client: IDotMatrixClient) -> None:
    await client.clock.show()
    await asyncio.sleep(1)
    await client.common.turn_off()


async def set_combo(client: IDotMatrixClient) -> None:
    """flip + brightness + DIY frame, the three states that stay independently
    readable at the same time (see the docstring's ONE PHYSICAL RUN note)."""
    await client.common.set_screen_flipped(True)
    await client.common.set_brightness(DIM_BRIGHTNESS)
    await client.display.show_frame(build_diy_frame())


@dataclass(frozen=True)
class Row:
    key: str
    label: str
    setter: Callable[[IDotMatrixClient], Awaitable[None]]
    look: str          # what the panel shows while the state IS in force
    reset_look: str    # what a RESETS TO CLOCK reading looks like
    automated: bool = True
    software_power_cycle: bool = True
    extra_question: str = ""  # row-specific question the four verdicts don't ask


CLOCK_LOOK = "the ordinary clock face, right way up, normal brightness"

ROWS: tuple[Row, ...] = (
    Row("clock", "clock (control row)", set_clock,
        "the ordinary clock face", CLOCK_LOOK),
    Row("diy", "DIY frame", set_diy,
        "BLUE block top-left, CYAN block bottom-right, small WHITE square near the TOP-RIGHT",
        CLOCK_LOOK),
    Row("color", "fullscreen colour", set_color,
        "the whole panel flat ORANGE", CLOCK_LOOK),
    Row("gif", "GIF playback", set_gif,
        "a small WHITE block hopping CLOCKWISE around the four corners "
        "(top-left -> top-right -> bottom-right -> bottom-left) on a dim GREEN field, 4 fps",
        CLOCK_LOOK,
        extra_question="IF IT IS STILL HOPPING: did it RESTART FROM THE FIRST CORNER "
                       "(top-left) or CONTINUE FROM WHERE IT WAS? That is the whole "
                       "difference between RESUMES and PERSISTS for this row.",),
    Row("text", "scrolling text", set_text,
        f"the word {TEXT_WORD} scrolling in MAGENTA", CLOCK_LOOK),
    Row("effect", "built-in effect", set_effect,
        "the built-in animation in RED and BLUE only", CLOCK_LOOK),
    Row("flip", "screen flip", set_flip,
        "the clock face UPSIDE DOWN", CLOCK_LOOK),
    Row("brightness", "brightness", set_brightness,
        f"flat WHITE, clearly DIM (brightness {DIM_BRIGHTNESS})",
        "flat WHITE at full glare, or the clock at full glare"),
    Row("eco", "eco configuration", set_eco,
        f"flat WHITE but DIM, because eco is holding it at {ECO_BRIGHTNESS} "
        f"even though brightness is {NEUTRAL_BRIGHTNESS}",
        "flat WHITE at full glare -- eco no longer applied"),
    # The software power cycle IS this row's state, so column 2 is meaningless
    # for it; the mains column is where it gets interesting.
    Row("power", "software power off", set_power,
        "the panel DARK -- nothing lit at all", CLOCK_LOOK,
        software_power_cycle=False),
    Row("combo", "flip + brightness + DIY frame together", set_combo,
        "DIM, and ROTATED 180: CYAN block top-left, BLUE block bottom-right, small WHITE "
        "square near the BOTTOM-LEFT",
        CLOCK_LOOK,
        automated=False),
)

ROWS_BY_KEY = {row.key: row for row in ROWS}
AUTOMATED_ROWS = tuple(row for row in ROWS if row.automated)

PREAMBLE_NONE, PREAMBLE_BLE, PREAMBLE_POWER = "none", "ble", "power"
PREAMBLES = (PREAMBLE_NONE, PREAMBLE_BLE, PREAMBLE_POWER)


@dataclass(frozen=True)
class AutoOptions:
    """The automated mode's prelude knobs, all resolved before any BLE contact.

    Defaults reproduce the original behaviour exactly: reset, no wait, no
    preamble. Equality against AutoOptions() is how parse_mode detects "a knob
    was passed" when rejecting them for set/check/restore.
    """

    delay: float = 0.0
    preamble: str = PREAMBLE_NONE
    skip_reset: bool = False


VERDICTS = (
    "PERSISTS             -- still in force, unchanged",
    "RESUMES              -- animation still running (say whether it restarted or continued)",
    "RESETS TO CLOCK      -- the clock face took over",
    "NEEDS A NEW COMMAND  -- gone, and nothing sensible took its place",
)


# --- shared device operations -----------------------------------------------

async def neutralize(client: IDotMatrixClient, acks: AckLog) -> None:
    """Power on, unflipped, brightness 100, eco off, clock. Every restore path
    and every phase entry goes through here, so no row inherits the previous
    row's state."""
    sent_at = time.perf_counter()
    await client.common.turn_on()
    await client.common.set_screen_flipped(False)
    await client.common.set_brightness(NEUTRAL_BRIGHTNESS)
    # eco_brightness is set high as well as disabled: if the enable bit were
    # ever misread by firmware, the window still could not dim anything.
    await client.eco.set_mode(
        enabled=False, start_hour=0, start_minute=0, end_hour=0, end_minute=0,
        eco_brightness=NEUTRAL_BRIGHTNESS,
    )
    await client.clock.show()
    await acks.settle_and_report("neutralize", sent_at)


async def interrupt_ble(client: IDotMatrixClient) -> None:
    """The BLE disconnect/reconnect interruption -- ONE definition.

    Both the row loop and --preamble call this, so a preamble interruption is
    byte-identical to the one a row performs. If these ever diverge, the
    preamble stops answering the question it exists to answer.
    """
    await client.disconnect()
    await asyncio.sleep(BLE_GAP_SECONDS)
    await client.connect()
    await asyncio.sleep(SETTLE_SECONDS)


async def interrupt_power(client: IDotMatrixClient, acks: AckLog, label: str) -> None:
    """The software power off/on interruption -- ONE definition. See interrupt_ble."""
    sent_at = time.perf_counter()
    await client.common.turn_off()
    await asyncio.sleep(POWER_OFF_SECONDS)
    await client.common.turn_on()
    await asyncio.sleep(SETTLE_SECONDS)
    await acks.settle_and_report(label, sent_at)


def print_verdict_menu(row: Row) -> None:
    print(f"  WHEN IT HELD  : {row.look}", flush=True)
    print(f"  WHEN IT RESET : {row.reset_look}", flush=True)
    for verdict in VERDICTS:
        print(f"    {verdict}", flush=True)
    if row.extra_question:
        print(f"    ?? {row.extra_question}", flush=True)


# --- mode: automated (columns 1 and 2) --------------------------------------

async def run_automated(client: IDotMatrixClient, acks: AckLog, rows: tuple[Row, ...],
                        options: "AutoOptions") -> None:
    print(f"automated run: {len(rows)} row(s) x "
          f"(BLE disconnect/reconnect, software power off/on)", flush=True)
    print(f"rows to run, in order: {', '.join(r.key for r in rows)}", flush=True)
    print(f"prelude: reset={'SKIPPED' if options.skip_reset else 'yes'}  "
          f"delay={options.delay:.0f}s  preamble={options.preamble}", flush=True)

    if options.skip_reset:
        # --no-reset asks the bigger question: is the shadow about common.reset()
        # at all, or about the FIRST content pushed on ANY fresh connection?
        print("\n*** --no-reset: common.reset() SKIPPED. The prelude is a clock baseline "
              "only, on a connection that has been re-initialised by nothing. ***", flush=True)
        try:
            sent_at = time.perf_counter()
            await client.clock.show()
            await acks.settle_and_report("clock baseline (no reset)", sent_at)
        except Exception as ex:
            print(f"  clock baseline FAILED (continuing): {ex!r}", flush=True)
    else:
        try:
            sent_at = time.perf_counter()
            await client.common.reset()   # 04 00 03 80, VERIFIED non-destructive
            await asyncio.sleep(4)
            await acks.settle_and_report("reset", sent_at)
        except Exception as ex:
            print(f"  reset FAILED (continuing): {ex!r}", flush=True)

    if options.delay:
        # Quiet time only: no sends, no disconnect, no power cycle. That is the
        # point -- it isolates ELAPSED TIME from the re-initialisation a
        # preceding row would also supply. Answer, 2026-07-27: time alone does
        # NOTHING (--delay 120 gif still died). See the RESET SHADOW section.
        print(f"\nwaiting {options.delay:.0f}s before the first row "
              f"(no commands sent during the wait) ...", flush=True)
        await asyncio.sleep(options.delay)

    if options.preamble != PREAMBLE_NONE:
        # One interruption, fired BEFORE any row establishes content, using the
        # row loop's own interruption code. Splits the two events a rescuing
        # preceding row performs together.
        print(f"\n-- PREAMBLE ({options.preamble}): a PREAMBLE, NOT a row interruption. "
              f"No row content exists yet; this fires before the first row establishes "
              f"anything, purely to re-initialise the device.", flush=True)
        try:
            if options.preamble == PREAMBLE_BLE:
                await interrupt_ble(client)
                print(f"  transport: {client.snapshot()!r}", flush=True)
            else:
                await interrupt_power(client, acks, "preamble power off/on")
            print(f"-- PREAMBLE ({options.preamble}) complete; rows start now --", flush=True)
        except Exception as ex:
            print(f"  PREAMBLE FAILED -- the run's premise is void, read results with care: {ex!r}",
                  flush=True)

    try:
        for row in rows:
            try:
                print(f"\n=== ROW {row.key}: {row.label}", flush=True)
                await neutralize(client, acks)

                sent_at = time.perf_counter()
                await row.setter(client)
                await acks.settle_and_report(f"{row.key} established", sent_at)
                print(f"  WATCH ({WATCH_SECONDS}s) BASELINE -- you should now see: {row.look}", flush=True)
                await asyncio.sleep(WATCH_SECONDS)

                # --- column 1: BLE disconnect / reconnect
                print(f"  -- INTERRUPTION 1: BLE disconnect, {BLE_GAP_SECONDS}s down, reconnect", flush=True)
                await interrupt_ble(client)
                print(f"  transport: {client.snapshot()!r}", flush=True)
                print(f"  WATCH ({WATCH_SECONDS}s) AFTER RECONNECT -- verdict for "
                      f"{row.key} x BLE reconnect:", flush=True)
                print_verdict_menu(row)
                await asyncio.sleep(WATCH_SECONDS)

                # --- column 2: software power off / on
                if not row.software_power_cycle:
                    print("  -- INTERRUPTION 2 SKIPPED: a software power cycle IS this row's "
                          "state, so the cell is meaningless. The mains column covers it.", flush=True)
                    continue
                print(f"  -- INTERRUPTION 2: software power off for {POWER_OFF_SECONDS}s, then on", flush=True)
                await interrupt_power(client, acks, f"{row.key} power off/on")
                print(f"  WATCH ({WATCH_SECONDS}s) AFTER POWER ON -- verdict for "
                      f"{row.key} x software power cycle:", flush=True)
                print_verdict_menu(row)
                await asyncio.sleep(WATCH_SECONDS)
            except Exception as ex:
                print(f"  ROW {row.key} FAILED: {ex!r}", flush=True)
    finally:
        # eco, flip, brightness and power all get put back here -- including
        # when a row raised, which is exactly when a stale eco window would
        # otherwise be left dimming the operator's desk.
        print("\nrestoring neutral state ...", flush=True)
        try:
            await neutralize(client, acks)
        except Exception as ex:
            print(f"  RESTORE FAILED -- check the panel by hand (eco, flip, brightness): {ex!r}", flush=True)

    print("\nautomated columns done. For the physical power-cycle column run:", flush=True)
    print("  python probes/probe_p11_persistence.py set   ->  pull the plug  ->  ... check", flush=True)


# --- mode: set (arm a state, then get out of the way) -----------------------

async def run_set(client: IDotMatrixClient, acks: AckLog, row: Row) -> None:
    print(f"arming row {row.key}: {row.label}", flush=True)
    try:
        await neutralize(client, acks)
        sent_at = time.perf_counter()
        await row.setter(client)
        await acks.settle_and_report(f"{row.key} established", sent_at)
    except Exception:
        print("  arming FAILED -- restoring neutral so nothing is left armed", flush=True)
        try:
            await neutralize(client, acks)
        except Exception as ex:
            print(f"  RESTORE ALSO FAILED -- check eco/flip/brightness by hand: {ex!r}", flush=True)
        raise

    record = {
        "state": row.key,
        "label": row.label,
        "look": row.look,
        "reset_look": row.reset_look,
        "armed_at": datetime.now().isoformat(timespec="seconds"),
        "eco_armed": row.key == "eco",
        "eco_window_minutes": ECO_WINDOW_MINUTES if row.key == "eco" else 0,
        "brightness": DIM_BRIGHTNESS if row.key in ("brightness", "combo") else NEUTRAL_BRIGHTNESS,
        "flipped": row.key in ("flip", "combo"),
        "powered_off": row.key == "power",
    }
    HANDOFF_PATH.write_text(json.dumps(record, indent=2), encoding="utf-8")

    print(f"\nARMED. The panel should now show: {row.look}", flush=True)
    print(f"handoff written: {HANDOFF_PATH}", flush=True)
    if record["eco_armed"]:
        print(f"eco window is live and ENDS in ~{ECO_WINDOW_MINUTES} minutes -- "
              f"do the power-cycle and the check inside that window", flush=True)
    print("\nNOW: pull the panel's power at the wall, wait a few seconds, plug it back in,", flush=True)
    print("let it boot, then run:  python probes/probe_p11_persistence.py check", flush=True)


# --- mode: check (after the operator's power-cycle) -------------------------

async def run_check(client: IDotMatrixClient, acks: AckLog, record: dict) -> None:
    armed_at = record.get("armed_at", "unknown")
    print(f"row under test : {record.get('label')}  ({record.get('state')})", flush=True)
    print(f"armed at       : {armed_at}", flush=True)
    print(f"flip armed     : {record.get('flipped')}", flush=True)
    print(f"brightness set : {record.get('brightness')}", flush=True)
    print(f"eco armed      : {record.get('eco_armed')}", flush=True)
    print(f"powered off    : {record.get('powered_off')}", flush=True)
    print("", flush=True)
    print(f"  IT PERSISTED IF THE PANEL SHOWS : {record.get('look')}", flush=True)
    print(f"  IT RESET IF THE PANEL SHOWS     : {record.get('reset_look')}", flush=True)
    for verdict in VERDICTS:
        print(f"    {verdict}", flush=True)
    print("", flush=True)
    print(f"holding for {CHECK_HOLD_SECONDS}s WITHOUT SENDING ANYTHING -- go look at the panel now.",
          flush=True)
    print("(reconnecting alone does not change what is displayed; nothing below is sent until "
          "the hold ends)", flush=True)
    await asyncio.sleep(CHECK_HOLD_SECONDS)

    if record.get("eco_armed"):
        print("\ndisabling eco (unconditional -- it is the only state that could outlive this run)",
              flush=True)
        try:
            sent_at = time.perf_counter()
            await client.eco.set_mode(
                enabled=False, start_hour=0, start_minute=0, end_hour=0, end_minute=0,
                eco_brightness=NEUTRAL_BRIGHTNESS,
            )
            await acks.settle_and_report("eco disable", sent_at)
        except Exception as ex:
            print(f"  ECO DISABLE FAILED -- do it by hand: {ex!r}", flush=True)

    print("\nBrightness, flip and content are deliberately LEFT AS THEY ARE so you can keep", flush=True)
    print("looking. When you are done:  python probes/probe_p11_persistence.py restore", flush=True)


# --- mode: restore ----------------------------------------------------------

async def run_restore(client: IDotMatrixClient, acks: AckLog) -> None:
    print("restoring: power on, unflipped, brightness 100, eco off, clock", flush=True)
    await neutralize(client, acks)
    print("done.", flush=True)


# --- entry point ------------------------------------------------------------

def take_option(argv: list[str], name: str, hint: str) -> tuple[list[str], str | None]:
    """Pulls `name VALUE` out of argv wherever it sits, returning the rest."""
    if name not in argv:
        return argv, None
    index = argv.index(name)
    if index + 1 >= len(argv):
        print(f"{name} needs a value, e.g. {hint}", flush=True)
        raise SystemExit(2)
    return argv[:index] + argv[index + 2:], argv[index + 1]


def take_flag(argv: list[str], name: str) -> tuple[list[str], bool]:
    """Pulls a valueless flag out of argv wherever it sits."""
    if name not in argv:
        return argv, False
    return [arg for arg in argv if arg != name], True


def take_auto_options(argv: list[str]) -> tuple[list[str], "AutoOptions"]:
    """Pulls the automated mode's knobs out of argv, returning the rest.

    All three exist to dissect the RESET SHADOW (see the module docstring).
    A preceding row rescues a doomed upload by supplying THREE things at once --
    elapsed time, a BLE reconnect, and a software power cycle -- so each knob
    supplies exactly one of them, alone:

        --delay N               elapsed time alone   (answered: does nothing)
        --preamble ble|power    one interruption alone, before any row
        --no-reset              removes the reset itself, to ask whether the
                                shadow was ever about common.reset() at all
    """
    argv, raw_delay = take_option(argv, "--delay", "--delay 120")
    argv, raw_preamble = take_option(argv, "--preamble", f"--preamble {PREAMBLE_BLE}")
    argv, skip_reset = take_flag(argv, "--no-reset")

    delay = 0.0
    if raw_delay is not None:
        try:
            delay = float(raw_delay)
        except ValueError:
            delay = -1.0
        if delay < 0:
            print(f"--delay must be a non-negative number of seconds, got {raw_delay!r}", flush=True)
            raise SystemExit(2)

    preamble = PREAMBLE_NONE
    if raw_preamble is not None:
        if raw_preamble not in PREAMBLES:
            print(f"unrecognized --preamble {raw_preamble!r}; accepted: {', '.join(PREAMBLES)}",
                  flush=True)
            raise SystemExit(2)
        preamble = raw_preamble

    return argv, AutoOptions(delay=delay, preamble=preamble, skip_reset=skip_reset)


def parse_mode(argv: list[str]) -> tuple[str, Row | None, tuple[Row, ...], "AutoOptions"]:
    """Mode selection and, for the automated mode, the row filter and knobs.

    Done before the device is touched so a typo cannot half-arm a state, leave
    an eco window behind, or burn a twelve-minute run on the wrong rows.
    """
    modes = ("no argument (all automated rows), "
             "[--delay N] [--preamble ble|power] [--no-reset] <row> [<row> ...], "
             "set [state], check, restore")
    states = ", ".join(row.key for row in ROWS)
    automated_keys = tuple(row.key for row in AUTOMATED_ROWS)
    argv, options = take_auto_options(argv)
    if not argv:
        return "auto", None, AUTOMATED_ROWS, options

    mode = argv[0]
    if mode in ("check", "restore", "set") and options != AutoOptions():
        print(f"--delay / --preamble / --no-reset apply to the automated mode only, not {mode}",
              flush=True)
        raise SystemExit(2)
    if mode in ("check", "restore"):
        if len(argv) > 1:
            print(f"{mode} takes no further arguments; modes: {modes}", flush=True)
            raise SystemExit(2)
        return mode, None, (), AutoOptions()
    if mode == "set":
        key = argv[1] if len(argv) > 1 else "combo"
        if len(argv) > 2 or key not in ROWS_BY_KEY:
            print(f"unrecognized state {key!r}; states: {states}", flush=True)
            raise SystemExit(2)
        return "set", ROWS_BY_KEY[key], (), AutoOptions()

    # Anything else is a row filter for the automated mode: keys in the order
    # given, REPEATS KEPT. `gif gif` runs the GIF row, then runs it again after
    # the first one's interruption cycle -- that repeat is the discriminator for
    # the reset-shadow finding, so deduping here would silently delete the
    # experiment (it did, 2026-07-27). `combo` is a set-mode-only row and is
    # still not accepted here.
    unknown = [key for key in argv if key not in automated_keys]
    if unknown:
        print(f"unrecognized row/mode {unknown}; rows: {', '.join(automated_keys)}", flush=True)
        print(f"modes: {modes}", flush=True)
        raise SystemExit(2)
    return "auto", None, tuple(ROWS_BY_KEY[key] for key in argv), options


def load_handoff() -> dict:
    if not HANDOFF_PATH.is_file():
        print(f"no handoff file at {HANDOFF_PATH}", flush=True)
        print("run `python probes/probe_p11_persistence.py set` first, then power-cycle the panel.",
              flush=True)
        raise SystemExit(2)
    return json.loads(HANDOFF_PATH.read_text(encoding="utf-8"))


async def main(mode: str, row: Row | None, rows: tuple[Row, ...], options: AutoOptions) -> None:
    record = load_handoff() if mode == "check" else {}
    print(f"mode: {mode}", flush=True)
    if mode == "auto":
        print(f"rows selected: {', '.join(r.key for r in rows)}", flush=True)
        print(f"delay: {options.delay:.0f}s   preamble: {options.preamble}   "
              f"reset: {'SKIPPED (--no-reset)' if options.skip_reset else 'yes'}", flush=True)
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, SCREEN) as client:
        acks = AckLog()
        unsubscribe = client.add_response_listener(acks.record)
        try:
            if mode == "auto":
                await run_automated(client, acks, rows, options)
            elif mode == "set":
                assert row is not None  # parse_mode guarantees it for this mode
                await run_set(client, acks, row)
            elif mode == "check":
                await run_check(client, acks, record)
            else:
                await run_restore(client, acks)
        finally:
            unsubscribe()
    print("disconnected.", flush=True)


asyncio.run(main(*parse_mode(sys.argv[1:])))
