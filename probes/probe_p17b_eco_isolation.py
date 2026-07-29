"""P17b -- eco mode, instrumented with a lux meter; then the clock-colour question.

Twelve numbered measurement phases, each a steady state held for 25 s, read with
a phone lux meter two inches from the panel. The ECO HALF IS NOW SETTLED (see
below). Phases 9-12, the clock-colour question, need EYES rather than a
photometer -- a lux meter cannot resolve hue, and the operator's light-tight
chamber excluded light in both directions, so they could not see those phases at
all. Re-running eight settled phases to reach the last four wastes eight
minutes, so this probe has two modes:

    python probes/probe_p17b_eco_isolation.py            # full 12-phase run
    python probes/probe_p17b_eco_isolation.py colour     # phases 9-12 only, ~2 min

SETTLED -- DO NOT RE-PROBE
--------------------------
From this probe's instrumented run (2026-07-27; lux, full-white field, 25 s
holds, phone 2 in from the panel in a light-tight chamber):

    white@100  65.84  |  white@40  62.28  |  white@5  4.69  |  white@100  65.83
    eco@5       4.55  |  eco off   65.94  |  eco@100  65.23  |  eco off    65.00

  * eco_brightness IS LIVE. The inert-parameter hypothesis this probe was built
    to test is FALSIFIED: 4.55 vs 65.23 lux is a 14x gap.
  * eco_brightness IS THE ORDINARY BRIGHTNESS SCALE -- eco@5 (4.55) matches
    brightness-5 (4.69), and eco@100 (65.23) matches brightness-100 (65.84). Not
    a separate or reduced scale.
  * ECO OFF RESTORES THE HOST'S BRIGHTNESS (65.94 and 65.00, both back at the
    100 reference). capabilities.py's claim survives evidence that could have
    falsified it.
  * The meter was sound: the two white@100 readings agree to 1 part in 6000.
  * THE PANEL'S RESPONSE IS COMPRESSED AT THE TOP, and this is the PANEL, not the
    sensor: white@40 (62.28) is within 6% of white@100 (65.84). A separate
    11-rung ladder run at BOTH 2 in and 4 in gave normalized curves agreeing
    within 1-2% at every rung, which rules out sensor saturation. Brightness
    50-100 all deliver identical output; the real usable range is 5 to ~42.
    Consistent with firmware doing min(255, percent * 6).

From this probe's first, by-eye run (2026-07-27):
  * ECO IS A ONE-SHOT DIM, NOT A CLAMP. A host set_brightness(100) sent into an
    ACTIVE eco window WON -- the white field went fully bright and stayed there.
    Eco sets brightness once when its window opens and never re-asserts.
  * THE ECO CONFIG IS AUTONOMOUS DEVICE STATE. The dim survived a 15 s
    disconnect with no host attached. A fresh client inherits an eco
    configuration it cannot read back -- a daemon can be handed a panel that
    silently overrode its brightness.

From P17 Part A (2026-07-27, probes/probe_p17_brightness_eco.py):
  * Brightness is IMMEDIATE and PERSISTENT in all four display modes (DIY frame,
    GIF, effect, clock). It applies the moment the command lands -- never
    redraw-gated -- and persists across mode changes until the next brightness
    command. Operator: "the panel is 100%, the picture draws and then changes to
    40%. If you then leave it there, the panel will stay there. Until you send
    another brightness command."

WHY PHASES 1-8 ARE STILL HERE
-----------------------------
They are answered, not deleted: the full run stays reproducible, and it is the
run that produced the table above. It also stays honest about how it got there.
The first attempt judged the A/B by EYE across 18 s gaps and the operator
reported "all the changes looked same to me... there were no changes in phase
3-4" -- human vision adapts within seconds and has nothing left to compare
against once the previous state is gone. That reading was INCONCLUSIVE, and it
happened to point at the wrong answer: instrumented, the same A/B shows a 14x
gap. Anyone re-reading this probe should see why the eye-only version was
replaced rather than trusted.

Phases 1-4 (white at 100, 40, 5, 100) are both the operator's yardstick and a
validity check ON THE SENSOR:

    IF WHITE AT 100, 40 AND 5 PERCENT DO NOT PRODUCE CLEARLY DISTINCT LUX
    READINGS, THE METER IS TOO COARSE FOR THIS PANEL AND THE WHOLE RUN IS VOID.

That check has to come first, because a flat A/B is otherwise ambiguous: it could
mean eco_brightness is inert, or it could mean the phone cannot resolve this
panel's levels at all. Phases 1 and 4 are the same commanded level at the two
ends of the ladder, so they also expose meter drift and any change in room light.
On the 2026-07-27 run they agreed to 1 part in 6000 and the ladder resolved 5%
from 100% by 14x, so the run was valid -- but note that 40% vs 100% came out
within 6%, which is the PANEL's compression, not a failed check.

In `colour` mode all eight of these are skipped. The baseline prelude is NOT
skipped: the colour phases depend on starting from eco OFF at a known brightness,
so the reset / eco-off / brightness-100 prelude runs in both modes.

THE ONE OPEN QUESTION: DOES ECO CHANGE THE CLOCK'S COLOUR?
-----------------------------------------------------------
During the first run the operator saw the CLOCK DIGITS RENDER MAGENTA while eco
was active, turning WHITE when eco ended. If eco alters RENDERING rather than
only brightness, then part of what we have been calling "dimmer" may be a colour
change, and capabilities.py's description of eco as a brightness feature is wrong
or at least incomplete. Phases 9-11 ask that and only that, with the operator
judging COLOUR and never level.

WHY THESE PHASES ARM ECO AT eco_brightness=100 -- DO NOT "FIX" THIS BACK TO 5.
Eco is fully armed and active in phase 10, with a window covering now; the only
thing removed is the DIMMING, because dimming is not what these phases measure.
We have now MEASURED that eco_brightness is simply the ordinary brightness scale
(eco@5 -> 4.55 lux vs brightness-5 -> 4.69 lux, see SETTLED above), so arming at
5 would put the clock at roughly 8% output and then ask the operator to judge
HUE on a barely-lit display. That is the same class of error as judging
BRIGHTNESS on a clock face, which is exactly what sank the first eco run. At
eco_brightness=100 the digits stay at full brightness, so COLOUR is the only
variable that can differ between phase 9 and phase 10.

CONFOUND, AND WHY PHASE 12 EXISTS: the first run used the SDK's default
`clock.show()`, which is style 0 -- STYLE_RGB_SWIPE_OUTLINE. By its own name that
style swipes colour through the digits on its own, with no eco involved. A
magenta digit under style 0 may therefore be the STYLE, not eco. So phases 9-11
pin STYLE_COLOR (3), the solid-colour face, and pass an explicit white colour so
that nothing inherited from an earlier probe can be mistaken for an eco effect.
CAVEAT: that STYLE_COLOR actually HONOURS the colour argument is UNVERIFIED on
this panel -- no probe has established what any clock style does with it. If the
face turns out to ignore it, phases 9-11 remain a valid before/after comparison
against each other and against style 0, but the word "pinned" is then an
intention rather than a guarantee. STYLE_OUTLINES (6) is the fallback for a
rerun. Phase 12 shows style 0 with eco OFF as the control: if the digits cycle
colours there with no eco anywhere, the magenta is explained and eco is
exonerated.

DESIGN
------
The operator cannot see stdout -- they watch the panel. Every phase is a short
scoreboard label, scoreboard.show(17, phase_number), held 3 s, followed by the
steady measurement field held HOLD_SECONDS (25 s). Left number is always 17
("this is P17b"), right is the phase number 1..12. NOTHING CHANGES DURING A
MEASUREMENT HOLD: the state is established and its acks are reported BEFORE the
hold starts, so the panel is motionless while the meter is being read.

The startup banner prints the numbered phase list in order, so the operator can
write lux values against phase numbers afterwards. That list and the run itself
come from ONE table (build_phases), so they cannot drift apart.

Brightness is pinned to 100 after calibration and left alone -- no ladder
anywhere near the eco phases; that was the second design fault of the first run.
The one exception is the deliberate re-pin between the A/B halves (after phase
6), so both halves start from the same commanded level whatever eco OFF turns
out to do. Phase 6's reading is taken and printed BEFORE that re-pin, so
re-pinning cannot launder a failure of eco OFF to restore.

Eco is time-window driven, so the window is built around datetime.now(). A
window that wraps midnight is warned about rather than silently producing a
meaningless null result.

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

ECO IS RESTORED TO A DISABLED, INERT CONFIGURATION IN A `finally` BLOCK, so it
runs even if a phase raises: eco.set_mode(False, 22, 0, 6, 0,
eco_brightness=100) -- disabled, an ordinary night window, and an eco brightness
of 100 so that even if some firmware path re-enabled it, it could not dim
anything. Then brightness 100 and the clock. A stranded eco window would dim the
operator's desk display for hours, which is why this is a `finally` and not the
last line of the happy path.

READOUT
-------
Phases 1-8 are ANSWERED (see SETTLED above); their readout is kept only so a
re-run can be checked against the recorded table. Meter validity first: 100 / 40
/ 5 must read clearly distinct and phase 4 must match phase 1, or the run is
void. Then lux(5) vs lux(7) is the A/B -- measured 4.55 vs 65.23, so
eco_brightness is live and is the ordinary brightness scale -- and phases 6 and 8
must both return to the phase-4 reference, which they did (65.94, 65.00).

CLOCK COLOUR (phases 9-11) -- the live question. Judged as COLOUR, never level;
all three phases sit at full brightness, so a level change is not on the table:
  * digits go MAGENTA (or any non-white hue) in phase 10 and back to WHITE in
    phase 11  => ECO ALTERS RENDERING INDEPENDENTLY OF BRIGHTNESS. A new
    capability fact, and capabilities.py's one-line "lowers brightness to a set
    level between a start and end time" description is incomplete.
  * digits stay WHITE across 9, 10 and 11  => eco touches BRIGHTNESS ONLY, and
    the magenta seen in run 1 came from the clock STYLE rather than from eco.
    Phase 12 confirms which.

Phase 12 (style 0, RGB swipe, eco OFF -- the control):
  * digits cycle colours here with NO eco active  => the magenta is the STYLE.
    Eco is exonerated on colour, and the lesson is that the SDK's default clock
    style is a colour-cycling face that must never be used as a colour baseline.
  * digits hold one steady colour under style 0  => the style is not the
    explanation and phase 10's result stands on its own.

USAGE
-----
    python probes/probe_p17b_eco_isolation.py            # full 12-phase run, ~7 min
    python probes/probe_p17b_eco_isolation.py colour     # phases 9-12 only, ~2 min
    python probes/probe_p17b_eco_isolation.py color      # same thing
    python probes/probe_p17b_eco_isolation.py lowlight   # phases 13-16 only, ~90 s

LOWLIGHT (2026-07-27): the magenta digits from the first P17 run were NOT eco
(phases 9-11 were identical at full brightness) and NOT the clock style (the
operator confirmed the face never changed across all four colour phases -- style
selection appears inert on this panel). Remaining hypothesis: at brightness 5,
roughly 8% output, the GREEN channel falls below its LED turn-on threshold while
red and blue still light, so white renders MAGENTA -- consistent with P13's
finding that RGB (1,1,1) reads as pure black. It matters because brightness 5-15
has just been recommended for a GlanceOS night mode, and dim white reading pink
would qualify that.

The mode is parsed BEFORE the device is touched, so a typo cannot half-run a
probe. `colour` mode keeps the phase NUMBERS 9-12 rather than renumbering them to
1-4: the operator's notes and the recorded results already refer to them by those
numbers, and a phase number that means two different things across two runs is
how evidence gets misfiled.

Full run: lux meter two inches from the panel, room monitor off, one reading per
numbered phase. Colour run: eyes, ordinary room light, watching hue only.

RESULT (2026-07-27): CLOSED for phases 1-12 (full run, colour mode). Phases
1-8: see the SETTLED table above this docstring -- eco_brightness is live,
is the ordinary brightness scale, eco OFF restores the host's pinned
brightness, and the panel's brightness curve is compressed at the top (50%
through 100% deliver near-identical output; usable range roughly 5-42, both
corroborated independently by probes/probe_brightness_curve.py's two-
distance ladder). Phases 9-12 (clock colour): the digits stayed WHITE across
eco OFF (9), eco ON at eco_brightness=100/no dimming (10), and eco OFF again
(11) -- ECO DOES NOT ALTER RENDERING, only brightness. Phase 12 (style 0,
eco OFF, the control) also showed no colour change under the same
conditions the operator watched for 9-11, and the operator confirmed the
face never visibly differed across all four colour phases -- STYLE
SELECTION APPEARS INERT on this panel, only styles 0 and 3 of the eight
defined values having been tried. That kills both candidate explanations for
the magenta digits seen in the earlier by-eye run (neither eco nor the
clock style), leaving the LOWLIGHT hypothesis (green channel dropping out
below its LED turn-on threshold at low brightness, consistent with P13's
(1,1,1) reading as black) as the leading, but still UNTESTED, explanation --
phases 13-16 (`lowlight` mode) were written to test it but were NOT run
tonight and remain open. capabilities.py's eco.set_mode and the new clock.
style_select entry carry these results.

VOID (2026-07-28): THE ENTIRE CLOCK-STYLE PART OF THAT RESULT IS WITHDRAWN AS A
BLOCK -- the style-inertness reading, the "STYLE_COLOR colours the BACKGROUND
with black digit cutouts" rendering model, and phases 9-12's lux figures alike.
P19 G3 (probes/probe_p19_g3_clock_styles.py) swept all eight styles UNLABELLED
and the operator saw eight DISTINCT faces; the red sweep (G3b) showed RED DIGITS
on every style with no background fill anywhere, and the vendor app agrees. The
cause of the error is this probe's own DESIGN: every phase here is separated by a
scoreboard label, and a scoreboard call is a native-mode command, so the panel
left and re-entered clock mode between phases and the style argument never got a
clean test. Worse, the lux appeared to corroborate the background claim -- 63-65
against a full white field's 65.8 -- but a label sitting on the panel produces
exactly that reading. THE LUX CORROBORATED THE LABEL, NOT THE STYLE; two
instruments agreeing is not validation when both share a confound. The phases
1-8 brightness/eco results are UNAFFECTED (no style argument in play), and this
probe's own CONFOUND note above turns out to have been right to flag that
STYLE_COLOR's handling of the colour argument was unverified.
"""

import asyncio
import sys
import time
from datetime import datetime, timedelta

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import clock as clock_protocol

ADDRESS = "6D:FD:F8:A0:3E:AF"

PROBE_NUMBER = 17          # scoreboard count1 on every label -- "this is P17b"

WHITE = (255, 255, 255)    # the measurement target: maximum lit area, always
PINNED = 100               # the level brightness is pinned to and left at

MODE_FULL = "full"         # all 12 phases (no argument)
MODE_COLOUR = "colour"     # phases 9-12 only
MODE_LOWLIGHT = "lowlight"  # phases 13-16 only
COLOUR_PHASE_NUMBERS = (9, 10, 11, 12)
LOWLIGHT_PHASE_NUMBERS = (13, 14, 15, 16)
LOWLIGHT_LEVELS = (100, 20, 10, 5)   # white field, eco off, judged for HUE not level
LOWLIGHT_HOLD_SECONDS = 15

# The A/B (phases 5 and 7): both ends of the firmware-valid 5..100 range (P13),
# same window, same white field, differing only in the parameter. ANSWERED
# 2026-07-27 -- 4.55 vs 65.23 lux, so eco_brightness is live and is the ordinary
# brightness scale. Kept so the full run stays reproducible.
ECO_LOW = 5
ECO_HIGH = 100

# The clock-colour block (phases 9-12) arms eco at ECO_HIGH, NOT ECO_LOW, and
# that is deliberate -- see the docstring section. eco_brightness is now measured
# to be the ordinary brightness scale, so arming at 5 would leave the digits at
# ~8% output and ask the operator to judge HUE on a barely-lit panel. Eco is
# still fully armed with a window covering now; only the dimming is removed, so
# COLOUR is the only variable between phases 9 and 10.
ECO_COLOUR_BLOCK = ECO_HIGH

# STYLE_COLOR (3) is the solid-colour face, passed an explicit white so nothing
# inherited from an earlier probe can be mistaken for an eco effect -- though
# whether the face honours the colour argument at all is UNVERIFIED on this panel.
# The SDK's DEFAULT is style 0 (STYLE_RGB_SWIPE_OUTLINE), which swipes colour
# through the digits by itself; that default is what run 1 used and it is the
# leading explanation of the magenta. Phase 12 shows it deliberately, as control.
CLOCK_STYLE = clock_protocol.STYLE_COLOR
CLOCK_CONTROL_STYLE = clock_protocol.STYLE_RGB_SWIPE_OUTLINE
CLOCK_COLOR = WHITE

LABEL_SECONDS = 3          # scoreboard label: short, then get out of the way
HOLD_SECONDS = 25          # every measurement hold: settle the meter, read it
ACK_SETTLE = 2.5           # never report an ack list sooner than this after a send

REPIN_AFTER_PHASE = 6      # see the A/B note in the module docstring


def select_mode(argv: list[str]) -> str:
    """Which block to run, from the command line. Parsed before the device is touched.

    No argument keeps the original behavior: all 12 phases. `colour` (or the
    American spelling) runs only the clock-colour block, phases 9-12, which is
    the one question the lux run could not answer. Anything else exits non-zero
    rather than guessing, so a typo cannot half-run a probe.
    """
    if not argv:
        return MODE_FULL

    accepted = "no argument (full 12-phase run), colour, color, lowlight"
    if len(argv) > 1:
        print(f"expected at most one argument; accepted: {accepted}", flush=True)
        raise SystemExit(2)
    if argv[0].lower() in ("colour", "color"):
        return MODE_COLOUR
    if argv[0].lower() == MODE_LOWLIGHT:
        return MODE_LOWLIGHT
    print(f"unrecognized argument {argv[0]!r}; accepted: {accepted}", flush=True)
    raise SystemExit(2)


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


def build_phases(client: IDotMatrixClient, window: tuple[int, int, int, int]):
    """The single ordered table that drives BOTH the startup list and the run.

    One source, so the numbers the operator writes lux values against cannot
    drift from the numbers the panel actually shows. Each entry is
    (number, short title for the banner, setup coroutine factory, what to read).

    Every setup leaves the panel in its final measured state BEFORE the hold
    begins -- nothing changes while the meter is being read.
    """

    async def white_at(level: int) -> None:
        await client.device.set_brightness(level)
        await client.color.show(WHITE)

    async def white_with_eco(enabled: bool, eco_brightness: int) -> None:
        await client.color.show(WHITE)
        await client.eco.set_mode(enabled, *window, eco_brightness=eco_brightness)

    async def clock_with_eco(enabled: bool, eco_brightness: int, style: int) -> None:
        await client.eco.set_mode(enabled, *window, eco_brightness=eco_brightness)
        await client.clock.show(style, show_date=True, hour24=True, color=CLOCK_COLOR)

    read_level = "READ LUX. Judge LEVEL"
    read_color = "READ THE DIGIT COLOUR (not the level)"

    return (
        (1, "white @ 100% -- calibration + meter check",
         lambda: white_at(100),
         f"{read_level}. This is the top reference"),
        (2, "white @ 40% -- calibration",
         lambda: white_at(40),
         f"{read_level}. Must read clearly BELOW phase 1, or the meter is too coarse"),
        (3, "white @ 5% -- calibration",
         lambda: white_at(5),
         f"{read_level}. Must read clearly BELOW phase 2, or THE RUN IS VOID"),
        (4, "white @ 100% -- back to the reference",
         lambda: white_at(PINNED),
         f"{read_level}. Must match phase 1; if it does not, the readings are not"
         f" comparable across this run (meter drift, or the room light changed)"),
        (5, f"white, eco ON, eco_brightness={ECO_LOW}   <-- A/B half A",
         lambda: white_with_eco(True, ECO_LOW),
         f"{read_level}. Compare with phase 7, which differs ONLY in this parameter"),
        (6, "white, eco OFF (after A)",
         lambda: white_with_eco(False, ECO_LOW),
         f"{read_level}. Back to the phase-4 reference => eco restores the host's"
         f" brightness; still dim => the eco value sticks"),
        (7, f"white, eco ON, eco_brightness={ECO_HIGH}  <-- A/B half B",
         lambda: white_with_eco(True, ECO_HIGH),
         f"{read_level}. SAME as phase 5 => the parameter is INERT and eco applies a"
         f" FIXED level. Brighter than phase 5 => the parameter works"),
        (8, "white, eco OFF (after B)",
         lambda: white_with_eco(False, ECO_HIGH),
         f"{read_level}. Second eco-OFF datapoint"),
        (9, "clock (solid-colour face, pinned WHITE), eco OFF",
         lambda: clock_with_eco(False, ECO_HIGH, CLOCK_STYLE),
         f"{read_color}. This is the colour baseline -- it should be WHITE"),
        (10, f"clock (same face), eco ON at eco_brightness={ECO_COLOUR_BLOCK} (no dimming)",
         lambda: clock_with_eco(True, ECO_COLOUR_BLOCK, CLOCK_STYLE),
         f"{read_color}. Eco is ARMED and ACTIVE but not dimming, so the digits stay"
         f" at full brightness and COLOUR is the only thing that can have changed"
         f" since phase 9. DID THE DIGIT COLOUR CHANGE? Any non-white hue => eco"
         f" alters RENDERING independently of brightness. Still white => eco touches"
         f" brightness only, and run 1's magenta was the clock STYLE"),
        (11, "clock (same face), eco OFF again",
         lambda: clock_with_eco(False, ECO_LOW, CLOCK_STYLE),
         f"{read_color}. Back to white => whatever phase 10 showed was eco-driven"
         f" and reversible"),
        (12, "clock STYLE 0 (RGB swipe), eco OFF  <-- the control",
         lambda: clock_with_eco(False, ECO_HIGH, CLOCK_CONTROL_STYLE),
         f"{read_color}. Colours CYCLING with no eco anywhere => the magenta was the"
         f" DEFAULT CLOCK STYLE all along, and eco is exonerated on colour"),
    ) + tuple(
        # lowlight: the same white field, eco OFF, walked down the brightness
        # scale. The question is HUE, not level -- see the docstring.
        (13 + step, f"white @ {level}% -- lowlight hue check",
         (lambda lv=level: white_at(lv)),
         "IS THE WHITE FIELD STILL WHITE, or has it shifted (pink / magenta / blue)?"
         " A shift means the RGB channels' LED turn-on thresholds DIVERGE at low"
         " drive -- green dropping out first would render white as magenta")
        for step, level in enumerate(LOWLIGHT_LEVELS)
    )


async def run_phase(
    client: IDotMatrixClient, log: AckLog, number: int, title: str, setup, question: str,
    hold: int = HOLD_SECONDS,
) -> None:
    """Label the phase on the panel, establish the state, THEN hold it still.

    The ack report happens before the hold deliberately: it sleeps ACK_SETTLE,
    which would otherwise eat into a window the operator is trying to read a
    steady value in. Once the hold starts, this probe sends nothing at all.
    """
    print(f"\n=== PHASE {number}: {title} -- scoreboard {PROBE_NUMBER} | {number}", flush=True)
    await client.scoreboard.show(PROBE_NUMBER, number)
    await asyncio.sleep(LABEL_SECONDS)

    sent_at = time.perf_counter()
    await setup()
    await log.report(f"phase {number} setup", sent_at)

    print(f"  HOLD {hold}s, PHASE {number}: {question}", flush=True)
    await asyncio.sleep(hold)


async def restore(client: IDotMatrixClient) -> None:
    """Leaves the panel in a state the operator can live with for the rest of the day.

    Disabled eco, an ordinary 22:00-06:00 window, and eco_brightness=100 -- so
    even if some firmware path re-enabled the window on its own, it could not
    dim anything. Then full brightness and the clock. Each step is guarded
    separately: failing to restore eco must not also cost us the clock.
    """
    for label, action in (
        ("eco disabled (window 22:00-06:00, eco_brightness 100 -- inert either way)",
         lambda: client.eco.set_mode(False, 22, 0, 6, 0, eco_brightness=100)),
        (f"brightness {PINNED}", lambda: client.device.set_brightness(PINNED)),
        ("clock", lambda: client.clock.show()),
    ):
        try:
            await action()
            print(f"restored: {label}", flush=True)
        except Exception as ex:
            print(f"*** RESTORE FAILED ({label}): {ex!r} -- CHECK THE PANEL BY HAND ***", flush=True)


def print_banner(mode: str, phases, start: datetime, end: datetime, now: datetime) -> None:
    """The operator's worksheet: the mode, then every phase number in order.

    Printed from the SAME filtered phase list the run then executes, so what the
    operator writes readings against is exactly what the panel will show.
    """
    print("=" * 78, flush=True)
    if mode == MODE_LOWLIGHT:
        print("P17b LOWLIGHT BLOCK -- phases 13-16 only. EYES: judge HUE, not level.", flush=True)
        print("Full-white field, eco OFF, brightness walked down 100 / 20 / 10 / 5.", flush=True)
        print("Does dim white stay WHITE, or shift pink/magenta as a channel drops out?", flush=True)
    elif mode == MODE_COLOUR:
        print("P17b COLOUR BLOCK -- phases 9-12 only. EYES, not a meter: judge HUE.", flush=True)
        print("Ordinary room light is fine. The digits stay at FULL brightness in every", flush=True)
        print("phase, so the only thing that can change between them is COLOUR.", flush=True)
    else:
        print("P17b FULL RUN -- lux meter ~2 inches from the panel, room monitor OFF.", flush=True)
        print("Phases 1-8 are already answered (see the docstring); 9-12 need eyes.", flush=True)
    print(f"Each phase: a {LABEL_SECONDS}s scoreboard label (17 | N), then {HOLD_SECONDS}s of a",
          flush=True)
    print("STEADY field. Nothing changes during a hold. One reading per phase.", flush=True)
    print("", flush=True)
    for number, title, _setup, _question in phases:
        print(f"  {number:>2}. {title}", flush=True)
    print("", flush=True)
    if mode == MODE_LOWLIGHT:
        print("Phase numbers 13-16 are new; nothing here overlaps the recorded results.", flush=True)
    elif mode == MODE_COLOUR:
        print("Phase numbers stay 9-12, matching the recorded results and your notes.", flush=True)
    else:
        print("METER VALIDITY CHECK FIRST: if phases 1 / 2 / 3 (white at 100 / 40 / 5) do", flush=True)
        print("NOT read clearly different, the sensor is too coarse for this panel and the", flush=True)
        print("WHOLE RUN IS VOID -- a flat A/B would then say nothing about eco_brightness.", flush=True)
        print("Phase 4 must also match phase 1, or the readings are not comparable.", flush=True)
    print(f"\neco window for this run: {start:%H:%M} -> {end:%H:%M} (now {now:%H:%M})", flush=True)
    print("=" * 78, flush=True)


async def main(mode: str) -> None:
    now = datetime.now()
    start = now - timedelta(minutes=2)
    end = now + timedelta(minutes=20)
    window = (start.hour, start.minute, end.hour, end.minute)

    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        log = AckLog()
        unsubscribe = client.add_response_listener(log.record)
        wanted = {
            MODE_COLOUR: COLOUR_PHASE_NUMBERS,
            MODE_LOWLIGHT: LOWLIGHT_PHASE_NUMBERS,
        }.get(mode, tuple(range(1, 13)))   # the full run is phases 1-12, as before
        phases = tuple(p for p in build_phases(client, window) if p[0] in wanted)
        hold = LOWLIGHT_HOLD_SECONDS if mode == MODE_LOWLIGHT else HOLD_SECONDS
        print_banner(mode, phases, start, end, now)

        if end.date() != start.date():
            print("*** WARNING: the eco window wraps midnight (start hour > end hour)."
                  " The firmware may treat that as an empty window and never dim."
                  " A DEAD WINDOW GIVES NO DIM IN EITHER HALF, which is a DIFFERENT reading"
                  " from 'both halves dim identically' -- do not conclude eco_brightness is"
                  " inert from it. Re-run away from midnight. ***", flush=True)

        try:
            # Known-state entry, in BOTH modes: reset (verified non-destructive),
            # settle, eco explicitly disabled, brightness pinned to 100. The
            # colour phases depend on starting from eco OFF at a known level just
            # as much as phase 1 does, so this prelude is never skipped -- only
            # the white-field calibration and the A/B are.
            try:
                print("\nresetting device to a known state ...", flush=True)
                await client.device.reset()
                await asyncio.sleep(4)
                await client.eco.set_mode(False, *window, eco_brightness=ECO_HIGH)
                await client.device.set_brightness(PINNED)
                await client.color.show(WHITE)
                await asyncio.sleep(3)
                print(f"baseline: eco off, full-white field at {PINNED}%.", flush=True)
            except Exception as ex:
                print(f"  reset/baseline FAILED: {ex!r}", flush=True)

            for number, title, setup, question in phases:
                try:
                    await run_phase(client, log, number, title, setup, question, hold)
                except Exception as ex:
                    print(f"  PHASE {number} FAILED: {ex!r}", flush=True)

                if number == REPIN_AFTER_PHASE:
                    # Phase 6's reading has been taken and printed above; this
                    # only guarantees the two A/B halves start from the same
                    # commanded level, whatever eco OFF turned out to do.
                    print(f"  (phase {number} recorded) re-pinning brightness to {PINNED} so the"
                          f" A/B halves share a reference", flush=True)
                    try:
                        await client.device.set_brightness(PINNED)
                        await asyncio.sleep(3)
                    except Exception as ex:
                        print(f"  re-pin FAILED: {ex!r}", flush=True)

            print("\nverdict to record:", flush=True)
            if mode == MODE_LOWLIGHT:
                print("  white stays WHITE down to 5 => channels share a turn-on threshold;"
                      " the magenta had some other cause and brightness 5-15 is safe for a"
                      " night mode.", flush=True)
                print("  white shifts pink/magenta as brightness drops => the GREEN channel"
                      " drops out first; note the level it starts at -- that is the floor a"
                      " night mode can use before the panel goes off-white.", flush=True)
            elif mode != MODE_COLOUR:
                print("  (lux, one value per phase number)", flush=True)
                print("  1/2/3 not clearly distinct, or 4 != 1 => RUN VOID, meter too coarse.",
                      flush=True)
                print("  lux(5) vs lux(7) is the A/B -- recorded 4.55 vs 65.23 on 2026-07-27,"
                      " so eco_brightness is LIVE and is the ordinary brightness scale.", flush=True)
                print("  6/8 back to the phase-4 reference => eco OFF restores host brightness.",
                      flush=True)
            if mode != MODE_LOWLIGHT:
                print("  (colour, judged by eye -- all four phases are at full brightness)",
                      flush=True)
                print("  10 shows a NON-WHITE hue while 9/11 stay white => eco alters RENDERING"
                      " independently of brightness; capabilities.py's eco description is"
                      " incomplete.", flush=True)
                print("  9/10/11 all white => eco touches BRIGHTNESS ONLY.", flush=True)
                print("  12 cycling colours with no eco => run 1's magenta was the DEFAULT CLOCK"
                      " STYLE.", flush=True)
        finally:
            # Restoration runs even if a phase raised: an eco window left armed
            # would keep dimming the operator's desk display, and a half-run
            # probe must not cost them that.
            unsubscribe()
            await restore(client)
            print("done.", flush=True)


asyncio.run(main(select_mode(sys.argv[1:])))
