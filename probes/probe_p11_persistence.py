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
    python probes/probe_p11_persistence.py shadow-recover     # pointer-or-payload, ~3 min
    python probes/probe_p11_persistence.py set                # arm `combo`, then exit
    python probes/probe_p11_persistence.py set gif            # arm one named state
    python probes/probe_p11_persistence.py check              # after the power-cycle
    python probes/probe_p11_persistence.py restore            # put the panel back

Row filter keys: clock, diy, color, gif, text, effect, flip, brightness, eco,
power. Repeats are KEPT and run again in place. `combo` is a set-mode row only
and is not accepted as a filter. An unrecognized key prints the accepted keys
and exits 2 before any BLE contact. The three prelude knobs -- `--delay N`,
`--preamble ble|power`, `--no-reset` -- apply to the automated mode only and
are rejected for set/check/restore/shadow-recover. They may appear in any
position.

LAZY DISPLAY-STATE PERSISTENCE
-----------------------------
CORRECTED AND CONSOLIDATED 2026-07-28. This section has now carried two wrong
names. It first read THE RESET SHADOW and blamed common.reset(); that was
disproven by `--no-reset gif`, which died identically, twice. It then read THE
FIRST-CONNECTION SHADOW and claimed display state set on a client session's
FIRST BLE connection was non-durable, scoped per-client-session. THAT IS ALSO
DISPROVEN and is retracted below.

PRIOR ART -- cited so this cannot be rediscovered a third time. Both readings
were elaborations of a panel property this lab had already measured:

    2026-07-12  "the device persists its current native mode to flash LAZILY
                 (dwell somewhere under ~3 min) and boots into the last
                 persisted mode"
    2026-07-17  "CLEAN BLE disconnect -> device exits DIY -> reverts to the
                 persisted screen in ~2s"

Together those account for nearly everything the run series below observed. The
session-scoped framing was an artifact of UNCONTROLLED ELAPSED TIME between
commands -- the operator typing between runs -- which nothing held constant
until probe_p19_g5_kill_event.py's `own-delayed` sequence.

THE MODEL. Display-mode state -- which content the panel is showing -- lives in
RAM when first written and is committed to flash LAZILY. A clean BLE disconnect
makes the device revert to its LAST PERSISTED mode. So content written and then
disconnected from too quickly is lost, and the panel comes back on whatever was
persisted, usually the clock. It renders correctly, it acks normally (StatusAck
... status=3, SAVED), and it goes with nothing in the ack stream indicating a
problem.

Content survives a disconnect/reconnect if EITHER of two INDEPENDENT SUFFICIENT
conditions holds. Neither is necessary.

    (A) DWELL -- enough time has passed since the write. Dies at ~8 s, across
        many runs and both content types. SURVIVES at 90 s
        (probe_p19_g5_kill_event.py `own-delayed`: the SAME session performs
        the write and the reconnect, so session identity is held constant and
        only the delay varies). Threshold is between 8 s and 90 s and is NOT
        YET BISECTED; the 07-12 "under ~3 min" figure is consistent.

    (B) A PRIOR DISCONNECT/RECONNECT EARLIER IN THE SAME SESSION.
        `--preamble ble gif` survives a reconnect only ~8 s after the upload,
        REPRODUCED TWICE (2026-07-27, 2026-07-28). On the 07-28 run the
        operator reported the animation CONTINUED FROM WHERE IT WAS rather than
        restarting -- the device did not re-initialise playback at all, it ran
        straight through the disconnect. The matched control `--no-reset gif`
        (no preamble, same ~8 s) reliably DIES. DWELL CANNOT EXPLAIN THIS: same
        8 s, opposite outcome. The effect is real and ITS MECHANISM IS OPEN.

A DYING RUN YIELDS EXACTLY ONE MEASUREMENT (methodology correction, operator-
caught): once INTERRUPTION 1 has killed the content, INTERRUPTION 2 is looking
at a clock that was already on screen, so that cell is VOID -- the same
void-cell flaw the DIY row hit in the matrix proper. Earlier write-ups here said
"clock after BOTH interruptions"; that overstated the evidence. It is also why
the claim is "lost at the next BLE RECONNECT" and not "...or power cycle": the
power-cycle half was never separately measured on a dying run.

EVERY RELEVANT RUN. This table is the whole basis of the model:

    run                  prior reconnect?  dwell before interruption  outcome
    gif (x2)             no                ~8 s                       DIED
    --delay 120 gif      no                ~8 s (120 s ran BEFORE)    DIED
    --no-reset gif (x2)  no                ~8 s                       DIED
    --no-reset color     no                ~8 s                       DIED
    --preamble power gif no (blink only)   ~8 s                       DIED
    --preamble ble gif   YES               ~8 s                   SURVIVED (*)
      (x2)
    clock gif, full      yes (prior row)   ~8 s                   SURVIVED
      row sweep
    g5 own-delayed       no                90 s                   SURVIVED
      (colour)
    g5 reconnect         n/a -- foreign    minutes                SURVIVED
    set brightness +     n/a               minutes                SURVIVED
      PHYSICAL power cut                                          (booted to it)

    (*) animation CONTINUED rather than restarting.

RULED OUT as the operative variable: common.reset() (`--no-reset` died twice,
re-run with no variables changed and reproduced exactly); a DEVICE POWER BLINK
over the same link (`--preamble power` blinks the panel dark and back and died,
so no cheap power-blink mitigation exists); ELAPSED TIME BEFORE THE WRITE
(`--delay 120` died); GIF-SPECIFIC MACHINERY (`--no-reset color` is a plain mode
set -- no chunked upload, no flash write, no payload at all -- and died the same
way, so what is lost is the CURRENT-MODE POINTER, broadly across display state);
and SESSION IDENTITY, retracted next.

RETRACTED -- THE PER-CLIENT-SESSION CLAIM. This section previously read "THE
SHADOW IS STRICTLY PER-CLIENT-SESSION (G1b, two instances, 2026-07-28)", on the
strength of foreign sessions failing to kill content they had not written. THAT
IS WITHDRAWN. Those runs all had minutes of elapsed time behind them, so they
satisfied condition (A) and prove nothing about session identity, and
`g5 own-delayed` then showed the SAME session failing to kill its own
90-second-old content. Session identity is not the variable, and no part of this
model is scoped to the client session, the transport instance, or the process.
Consequence for integrators: multiple clients CAN share this panel, but the
reason is DWELL, not ownership.

THE ORGANIZING MODEL: CONFIG-CLASS device state (RTC, alarms, schedules,
brightness) and STORED PAYLOADS (GIF bytes in flash) commit durably and PROMPTLY
on any connection. DISPLAY-CLASS state -- the current-mode pointer alone --
commits LAZILY, and it is the only thing at risk.

BRIGHTNESS IS CONFIG-CLASS (G1, `--no-reset brightness`, 2026-07-28, two runs;
run 2 is the record). The row arms a flat WHITE field at brightness 10 -- two
variables on one screen, which is the point of it. Operator: clock at full
brightness -> WHITE, DIM (baseline) -> CLOCK, STILL DIM (after the BLE
reconnect) -> full brightness at the restore. The white field died at the
reconnect, display-class as expected; THE DIMMING SURVIVED, and survived the
software power cycle after it too, and separately survived a PHYSICAL mains
power cut. That second cell IS valid here, unlike a dying run's: the void rule
applies only to state interruption 1 had already killed, and brightness was
still in force going in. Pinning brightness once at startup is safe.

POINTER-NOT-PAYLOAD, CONFIRMED (G2, `shadow-recover`, 2026-07-28). Only the
current-mode pointer is committed lazily; the stored/flash payload commits
promptly and normally. See THE `shadow-recover` MODE below for the run and its
reading. SDK recovery rule: RE-ACTIVATE, DO NOT RE-TRANSFER.

THE `shadow-recover` MODE
------------------------
THE MODE NAME IS A LEGACY LABEL from the retracted "shadow" model. It is kept
because it is the CLI handle this probe is invoked with and is cited by name in
capabilities.py and docs/PROBE_PLAN.md; read it as "short-dwell recovery".

WHEN A SHORT-DWELL WRITE IS LOST, IS ONLY THE CURRENT-MODE POINTER GONE, OR THE
STORED PAYLOAD WITH IT? One run, on a fresh client, with NO common.reset():

    1. upload the 4-corner hop GIF   -> WATCH: the hop (the short-dwell write)
    2. BLE disconnect / reconnect    -> WATCH: expected the CLOCK (the loss)
    3. gif.activate_stored(), on the POST-reconnect session, with the SAME
       bytes and NO re-upload        -> WATCH: does the hop come back?
    4. BLE disconnect / reconnect    -> WATCH: this session now holds BOTH a
                                        prior reconnect and dwell, so the hop
                                        is expected to be durable

    Step 3 HOP RETURNS  => pointer-not-payload CONFIRMED. The pointer is
                           dropped and the stored gif is left in flash. SDK
                           recovery guidance becomes RE-ACTIVATE, DO NOT
                           RE-TRANSFER -- a ~1 s single-chunk CRC hit instead
                           of a whole upload.
    Step 3 STAYS CLOCK  => the payload went with the pointer (or the CRC slot
                           was cleared); recovery needs a real re-upload, and
                           activate_stored is no use after such a loss.
                           activate_stored's own return value is printed and
                           is the second half of this reading: False means the
                           device did not recognize the CRC at all.
    Step 4 HOP HOLDS    => the ordinary protected durability result, and the
                           control that says step 3's restore was real rather
                           than a repaint that would have died on its own.

RESULT (2026-07-28): HOP -> CLOCK -> HOP -> HOP. POINTER-NOT-PAYLOAD CONFIRMED.
Step 3's activate_stored() returned True -- the device recognized its stored CRC
and never asked for a re-transfer -- and the animation ACTUALLY RENDERED, which
on this panel is the distinction that matters. Step 4 held, so the restore is
durable and step 3 was a real recovery rather than a transient. NOTHING IS
DESTROYED: what is committed lazily is only the device's "what am I displaying"
state. RECOVERY RULE, now evidence-backed: RE-ACTIVATE, DO NOT RE-TRANSFER --
one small command instead of a whole chunked upload. SCOPE CAVEAT: this was
shown for stored GIFs, which HAVE a re-activate path. It does not generalise to
display-class content that has none -- a parked DIY still (DIY-clear -> frame ->
QUIT_STILL) has no "activate what you already have" command, so that path has no
equivalent recovery and must rely on dwell or a prior reconnect.

CONSISTENT-WITH: the 2026-07-17 persistence probes had fullscreen colour survive
THREE DAYS including power cycles -- pushed once and then left alone for days,
i.e. condition (A) satisfied with room to spare.

NOT "everything written on a first connection is volatile" -- that framing is
retracted entirely, but the alarm result that bounded it still stands. ALARMS
ARE UNAFFECTED: P6 Q4 armed both alarm slots in their own process and after a
PHYSICAL power cycle both fired with payloads intact (red+beep 12:34, blue
12:35). Alarm and schedule flash writes commit promptly; only display /
current-mode state is committed lazily.

MECHANISM OF THE PRIOR-RECONNECT RESCUE: OPEN, and the one genuinely unexplained
piece left. interrupt_ble calls client.disconnect() then client.connect() -- the
SAME connect() used for the initial connection, and IDotMatrixClient.connect()
only awaits BleTransport.connect() (no clock command, no set_time), so these are
not two different client code paths at the API level. A read of transport/ble.py
closes the one remaining suspicion on our side: connect() does NOT branch on a
cached BLEDevice. Discovery runs only when no MAC was given, this probe always
passes one, and every call builds a fresh BleakClient and re-subscribes
identically. Nothing in our stack distinguishes the two connections, so if
anything does, the DEVICE does; an HCI capture comparing connection 1 with
connection 2 is queued in docs/PROBE_PLAN.md P19 as the definitive tool.

MITIGATION: none is in the driver, and the cheap one is off the table.
`--preamble power gif` was the discriminator -- turn_off / turn_on over the SAME
BLE connection, no disconnect -- and it DIED, so a power blink in a caller's
startup handshake would buy nothing. The two known protections are to let
content DWELL, or to perform a genuine throwaway connect / disconnect /
reconnect. For stored GIFs there is a cheaper answer than either: G2's recovery
rule, re-activate rather than re-transfer.

The preamble deliberately calls the row loop's own interrupt_ble /
interrupt_power, so a preamble interruption is byte-identical to a row's.

The full automated run takes roughly 11-13 minutes and needs no one present;
one row is about 60-75 s, so `gif gif` is about 3 minutes, `--preamble ble gif`
about 100 s and `--no-reset gif` about 85 s. Re-testing a single row used to
cost the whole run, which is why the filter exists.

RESULT (2026-07-27): both automated columns ran, every row. On the BLE-reconnect
column only the DIY frame reset to the clock; every native mode held. READ THOSE
CELLS AS PROTECTED RESULTS -- the sweep arms its rows in sequence, so from the
second row onwards each state was established after an earlier disconnect/
reconnect in the same process, i.e. under condition (B). The clock control row
is additionally vacuous as a durability test (a clock dying to a clock is
undetectable). The DIY x software-power-cycle cell is VOID (the state was never
re-armed between the two interruptions); the PHYSICAL power-cycle column is
unrun for every row. Full account in capabilities.py's
display.persistence_matrix.

RESULT (2026-07-28, P19 night session): G1 brightness is CONFIG-CLASS
(`--no-reset brightness`, two runs) and G2 POINTER-NOT-PAYLOAD confirmed
(`shadow-recover`), so the recovery rule is re-activate, not re-transfer. Both
are recorded above in full. G1b -- "the shadow is strictly per-client-session"
-- was recorded here too and is now RETRACTED; see the retraction above.
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
    await client.device.set_screen_flipped(True)
    await client.clock.show()


async def set_brightness(client: IDotMatrixClient) -> None:
    await client.color.show(WHITE)
    await client.device.set_brightness(DIM_BRIGHTNESS)


async def set_eco(client: IDotMatrixClient) -> None:
    """Arms an eco window covering now, ENDING 20 minutes from now.

    The bounded end is the safety property: if the operator abandons the run
    between `set` and `check`, the panel un-dims itself rather than sitting at
    eco_brightness on someone's desk all evening.
    """
    await client.color.show(WHITE)
    await client.device.set_brightness(NEUTRAL_BRIGHTNESS)
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
    await client.device.turn_off()


async def set_combo(client: IDotMatrixClient) -> None:
    """flip + brightness + DIY frame, the three states that stay independently
    readable at the same time (see the docstring's ONE PHYSICAL RUN note)."""
    await client.device.set_screen_flipped(True)
    await client.device.set_brightness(DIM_BRIGHTNESS)
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
    await client.device.turn_on()
    await client.device.set_screen_flipped(False)
    await client.device.set_brightness(NEUTRAL_BRIGHTNESS)
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
    await client.device.turn_off()
    await asyncio.sleep(POWER_OFF_SECONDS)
    await client.device.turn_on()
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
        # --no-reset asked whether the loss was about common.reset() at all.
        # ANSWERED 2026-07-27: it never was -- this died twice, identically to
        # the runs that did reset. Kept as the reproduction path, and as the
        # matched ~8s control that `--preamble ble` is read against.
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
            await client.device.reset()   # 04 00 03 80, VERIFIED non-destructive
            await asyncio.sleep(4)
            await acks.settle_and_report("reset", sent_at)
        except Exception as ex:
            print(f"  reset FAILED (continuing): {ex!r}", flush=True)

    if options.delay:
        # Quiet time only: no sends, no disconnect, no power cycle. NOTE the
        # delay runs BEFORE the write, so it measures elapsed time preceding the
        # content, NOT dwell after it -- 2026-07-27's `--delay 120 gif` died,
        # which is why time-before-the-write is ruled out while DWELL is
        # condition (A). See LAZY DISPLAY-STATE PERSISTENCE above.
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


# --- mode: shadow-recover (pointer or payload?) -----------------------------

SHADOW_RECOVER_HOP = ("a small WHITE block hopping CLOCKWISE around the four corners "
                      "(top-left -> top-right -> bottom-right -> bottom-left) on a dim GREEN "
                      "field, 4 fps")


def print_shadow_recover_script() -> None:
    """EVERY visual of the run, in order, before any BLE contact.

    Exhaustive including the states that are merely setup. An operator who is
    not told about a baseline sees their first frame contradict their brief and
    stops trusting the rest of the run -- that is the single biggest cause of a
    wasted panel session in this lab.
    """
    print("", flush=True)
    print("=== shadow-recover: WHAT YOU WILL SEE, IN ORDER =============================", flush=True)
    print("  0. BEFORE ANYTHING: whatever the panel is showing right now is LEFT ALONE.", flush=True)
    print("     No reset, no clock command, no brightness change -- the whole point is", flush=True)
    print("     that the GIF is written and then disconnected from a few seconds later,", flush=True)
    print("     with nothing else in the way.", flush=True)
    print(f"  1. THE HOP ({WATCH_SECONDS}s): {SHADOW_RECOVER_HOP}.", flush=True)
    print("     This is the short-dwell write: it will not have been persisted yet.", flush=True)
    print(f"  2. A ~{BLE_GAP_SECONDS}s GAP while the link is down. The panel keeps showing", flush=True)
    print("     whatever it was showing; nothing is sent during the gap.", flush=True)
    print(f"  3. AFTER RECONNECT ({WATCH_SECONDS}s): EXPECTED the ordinary CLOCK FACE -- the", flush=True)
    print("     panel reverting to its last PERSISTED mode. If the hop is still there,", flush=True)
    print("     it dwelt long enough after all and everything after step 3 is void;", flush=True)
    print("     say so.", flush=True)
    print(f"  4. AFTER activate_stored ({WATCH_SECONDS}s): THE QUESTION. Does the hop come", flush=True)
    print("     BACK, with no re-upload? Hop = the stored payload survived and only the", flush=True)
    print("     mode pointer was lost. Still the clock = the payload went too.", flush=True)
    print(f"  5. A second ~{BLE_GAP_SECONDS}s GAP, then AFTER RECONNECT ({WATCH_SECONDS}s):", flush=True)
    print("     this session now has BOTH a prior reconnect and dwell behind it, so", flush=True)
    print("     whatever step 4 left up is expected to still be there. Control on step 4.", flush=True)
    print("  6. RESTORE: power on, unflipped, brightness 100, eco off, and the CLOCK.", flush=True)
    print("     That final clock is cleanup, NOT a result.", flush=True)
    print("=============================================================================", flush=True)


async def run_shadow_recover(client: IDotMatrixClient, acks: AckLog) -> None:
    """Pointer-or-payload: after a short-dwell GIF is lost, can it be re-ACTIVATED?

    Deliberately sends NOTHING before the upload -- no reset, no clock baseline
    -- because any earlier command would be the display state the reconnect
    reverts to, instead of the clock, and the reading would be ambiguous.
    """
    gif_bytes = build_test_gif()
    print(f"\nfixture: {len(gif_bytes)}B, the same 4-corner hop the gif row uses.", flush=True)
    print("nothing has been sent to the panel yet -- the upload below is this session's "
          "FIRST command.", flush=True)

    try:
        print("\n=== STEP 1: upload the hop, nothing before it (no reset, no baseline)",
              flush=True)
        sent_at = time.perf_counter()
        await client.gif.upload_bytes(gif_bytes)
        await acks.settle_and_report("gif upload", sent_at)
        print(f"  WATCH ({WATCH_SECONDS}s) BASELINE -- you should now see: {SHADOW_RECOVER_HOP}",
              flush=True)
        await asyncio.sleep(WATCH_SECONDS)

        print(f"\n=== STEP 2: BLE disconnect, {BLE_GAP_SECONDS}s down, reconnect", flush=True)
        await interrupt_ble(client)
        print(f"  transport: {client.snapshot()!r}", flush=True)
        print(f"  WATCH ({WATCH_SECONDS}s) -- EXPECTED: {CLOCK_LOOK}, i.e. the panel reverted to "
              f"its last PERSISTED mode. Still hopping => the write dwelt long enough after "
              f"all; the rest of this run is void.",
              flush=True)
        await asyncio.sleep(WATCH_SECONDS)

        print("\n=== STEP 3: gif.activate_stored() with the SAME bytes -- NO re-upload", flush=True)
        sent_at = time.perf_counter()
        recognized = await client.gif.activate_stored(gif_bytes)
        print(f"  activate_stored returned {recognized!r} "
              f"(True = the device recognized its stored CRC)", flush=True)
        await acks.settle_and_report("activate_stored", sent_at)
        print(f"  WATCH ({WATCH_SECONDS}s) -- THE QUESTION: is the hop BACK?", flush=True)
        print("    HOP        -- the stored payload SURVIVED; only the current-mode pointer "
              "was lost. Recovery = re-activate, not re-transfer.", flush=True)
        print("    CLOCK      -- the payload went with the pointer; activate_stored is no use "
              "after such a loss.", flush=True)
        await asyncio.sleep(WATCH_SECONDS)

        print(f"\n=== STEP 4: control -- BLE disconnect, {BLE_GAP_SECONDS}s down, reconnect",
              flush=True)
        await interrupt_ble(client)
        print(f"  transport: {client.snapshot()!r}", flush=True)
        print(f"  WATCH ({WATCH_SECONDS}s) -- this session has reconnected twice now and the "
              f"content has dwelt, so it is PROTECTED on both counts. Whatever step 3 left up "
              f"is expected to STILL BE THERE; if it vanished, step 3's restore was not durable "
              f"and says nothing about recovery.",
              flush=True)
        await asyncio.sleep(WATCH_SECONDS)
    finally:
        print("\nrestoring neutral state ...", flush=True)
        try:
            await neutralize(client, acks)
        except Exception as ex:
            print(f"  RESTORE FAILED -- check the panel by hand (eco, flip, brightness): {ex!r}",
                  flush=True)


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

    All three exist to dissect DISPLAY-STATE DURABILITY (see the module
    docstring). A preceding row protects a doomed upload by supplying THREE
    things at once -- elapsed time, a BLE reconnect, and a software power cycle
    -- so each knob supplies exactly one of them, alone:

        --delay N               elapsed time alone, BEFORE the write (answered:
                                does nothing; dwell AFTER the write is what
                                matters, and this knob cannot supply it)
        --preamble ble|power    one interruption alone, before any row
                                (ble: answered, it protects -- condition (B);
                                power: answered, it does NOT, a same-connection
                                power blink buys nothing)
        --no-reset              removes the reset itself, to ask whether the
                                loss was ever about common.reset() at all
                                (answered: it never was)
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
             "shadow-recover, set [state], check, restore")
    states = ", ".join(row.key for row in ROWS)
    automated_keys = tuple(row.key for row in AUTOMATED_ROWS)
    argv, options = take_auto_options(argv)
    if not argv:
        return "auto", None, AUTOMATED_ROWS, options

    mode = argv[0]
    if mode in ("check", "restore", "set", "shadow-recover") and options != AutoOptions():
        print(f"--delay / --preamble / --no-reset apply to the automated mode only, not {mode}",
              flush=True)
        raise SystemExit(2)
    if mode in ("check", "restore", "shadow-recover"):
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
    # the first one's interruption cycle -- that repeat is the discriminator
    # for condition (B), so deduping here would silently delete the experiment
    # (it did, 2026-07-27). `combo` is a set-mode-only row and is still not
    # accepted here.
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
    if mode == "shadow-recover":
        print_shadow_recover_script()
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
            elif mode == "shadow-recover":
                await run_shadow_recover(client, acks)
            else:
                await run_restore(client, acks)
        finally:
            unsubscribe()
    print("disconnected.", flush=True)


asyncio.run(main(*parse_mode(sys.argv[1:])))
