"""P19 G3 -- the clock style sweep: are any of the eight styles distinguishable?

WHY THIS PROBE EXISTS
---------------------
capabilities.py's clock.style_select sits at UNKNOWN on two samples. Styles 0
(STYLE_RGB_SWIPE_OUTLINE) and 3 (STYLE_COLOR) are the only values ever put on
this panel, both in probe_p17b_eco_isolation.py phases 9-12, and the operator
could not tell them apart. Styles 1, 2, 4, 5, 6 and 7 (protocol/clock.py) have
never been sent at all. "Style selection appears inert" cannot ship on 2 of 8
values, and neither can the opposite claim.

So: all eight, in order, ~10 s each, one connection, nothing else touched.

WHY THERE ARE NO LABELS BETWEEN PHASES
--------------------------------------
Every other probe in this lab narrates itself on the panel with a scoreboard
frame between phases. THAT IS FATAL HERE. A scoreboard call is itself a
native-mode command: it takes the display away from the clock, and the next
clock.show() re-enters clock mode from scratch. A sweep narrated that way would
measure "does re-entering clock mode redraw the face" -- which it obviously does
-- and would tell us nothing about whether the STYLE ARGUMENT changes anything.

The sweep therefore sends clock.show() and NOTHING ELSE, eight times, back to
back. The panel never leaves clock mode for the whole run. The cost is that the
operator watches an UNANNOUNCED sequence: no number appears on the panel to say
which style is up.

That cost is paid back on the console. Every phase prints a numbered line with a
WALL-CLOCK TIMESTAMP as it is sent, so the run can be reconstructed afterwards
from the console log plus what the operator saw and when.

WHAT THE OPERATOR HAS TO DO
---------------------------
Watch the panel continuously for ~80 s and answer TWO questions:

  1. HOW MANY VISUALLY DISTINCT CLOCK FACES appeared in total? (Eight changes
     of style; possibly one face, possibly eight, possibly something between.)
  2. AT WHICH TRANSITIONS did a change happen? "It changed once, roughly a
     third of the way through" is a usable answer -- the console timestamps
     turn it into a style number afterwards.

Do NOT read seconds off the panel to time anything: this panel's clock face has
NO SECONDS DISPLAY, only hours and minutes. Judge the transitions by watching,
not by timing them.

CONSTANTS HELD FIXED, so style is the only variable
---------------------------------------------------
colour WHITE, show_date True, hour24 True, and no brightness/flip/eco command
anywhere in the run. Colour matters more than it looks: STYLE_COLOR (3) colours
the BACKGROUND and renders the digits as black cutouts, so passing white to it
paints a white background -- which is exactly how the P17b run misread this
feature as "the digits were white throughout". If a phase looks like a solid
bright panel with dark digits, that is a REAL and DISTINCT face, not a failure;
say so.

ACK DISCIPLINE
--------------
Each send is timestamped, given a SETTLE_SECONDS (2.5 s) wait BEFORE the ack
list is read, and reported with its send->ack delta. The list is never cleared:
each phase reports only the slice that arrived since its own mark, so a late
reply lands in a later phase's report instead of being destroyed. That is the
bug that voided probe_effect_length_byte2.py's headline finding.

SAFETY
------
Sends nothing but clock.show(). No reset, no brightness, no eco, no flip, no
RTC write, no experimental namespace, no password or UART surface. The panel is
left on style 0 with the ordinary white face, which is the neutral state every
other probe starts from.

USAGE
-----
    python probes/probe_p19_g3_clock_styles.py sweep

The argument is mandatory and selects exactly one sequence; `sweep` is the only
one. Runtime ~90 s including connect. The operator must be able to watch the
panel continuously from the moment the banner says the sweep is starting.

RESULT (2026-07-__): pending.
"""

import asyncio
import sys
import time
from datetime import datetime

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import clock as clock_protocol

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

# Read the ack list only after this long -- never before, and never clear it.
SETTLE_SECONDS = 2.5
STYLE_SECONDS = 10.0  # per style, including the settle window

WHITE = (255, 255, 255)

# protocol/clock.py's own names, in wire order. The sweep runs them in this
# order and the console commentary prints the name with the number, so a
# console log alone is enough to reconstruct which face was up when.
STYLES: tuple[tuple[int, str], ...] = (
    (clock_protocol.STYLE_RGB_SWIPE_OUTLINE, "STYLE_RGB_SWIPE_OUTLINE (previously tried)"),
    (clock_protocol.STYLE_CHRISTMAS_TREE, "STYLE_CHRISTMAS_TREE (never sent before)"),
    (clock_protocol.STYLE_CHECKERS, "STYLE_CHECKERS (never sent before)"),
    (clock_protocol.STYLE_COLOR, "STYLE_COLOR (previously tried: white BACKGROUND, black digits)"),
    (clock_protocol.STYLE_HOURGLASS, "STYLE_HOURGLASS (never sent before)"),
    (clock_protocol.STYLE_ALARM_CLOCK, "STYLE_ALARM_CLOCK (never sent before)"),
    (clock_protocol.STYLE_OUTLINES, "STYLE_OUTLINES (never sent before)"),
    (clock_protocol.STYLE_RGB_CORNERS, "STYLE_RGB_CORNERS (never sent before)"),
)

# RED, not white, for the colour-attribution sweep. White is useless for asking
# WHERE the colour argument lands, because a white-digits-on-black face and a
# white-background-with-black-digits face are both "white and black" to a tired
# operator -- which is how STYLE_COLOR was first read. A saturated hue makes
# "red digits" and "red background" impossible to confuse.
RED = (255, 0, 0)

# Which colour each sequence sweeps with. Everything else about the run is
# identical, so colour is the only variable between them.
SEQUENCE_COLOURS = {"sweep": WHITE, "sweep-red": RED}

SEQUENCES = {
    "sweep": "all eight styles, in wire order 0..7, ~10 s each, unlabelled, colour WHITE",
    "sweep-red": "the same eight styles, colour RED -- asks WHERE the colour argument lands",
}


def print_usage() -> None:
    print("usage: python probes/probe_p19_g3_clock_styles.py <sequence>", flush=True)
    print("", flush=True)
    print("Runs exactly ONE sequence. The argument is mandatory.", flush=True)
    for key, description in SEQUENCES.items():
        print(f"    {key:8s} {description}", flush=True)


def select_sequence(argv: list[str]) -> str:
    """Validated before any BLE contact, so a typo cannot burn a panel session."""
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


def print_visual_script(colour_name: str) -> None:
    """EVERY visual of the run, in order, printed before any BLE contact.

    Exhaustive on purpose, INCLUDING the states that are only setup. An operator
    who was not told about a baseline sees their first frame contradict their
    brief and stops trusting the run -- the single biggest cause of a wasted
    panel session in this lab.
    """
    total = len(STYLES) * STYLE_SECONDS
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER =============================================", flush=True)
    print("  0. BEFORE THE SWEEP: whatever the panel is showing right now stays up while", flush=True)
    print("     the client connects (a few seconds). Nothing is sent to change it, and", flush=True)
    print("     it is NOT part of the measurement. Most likely the ordinary clock face.", flush=True)
    print(f"  1. THE SWEEP: {len(STYLES)} clock faces, {STYLE_SECONDS:.0f} s each, "
          f"{total:.0f} s in total.", flush=True)
    print("     THEY ARE NOT LABELLED. No number, no scoreboard, no text appears on the", flush=True)
    print("     panel at any point -- a label would be a native-mode command and would", flush=True)
    print("     wreck the very thing being measured. The panel stays in clock mode the", flush=True)
    print("     whole time and only the STYLE ARGUMENT changes underneath it.", flush=True)
    print(f"     Colour is held at {colour_name} for all eight, date and 24h on, so style", flush=True)
    print("     is the only variable WITHIN a run. Comparing the two sequences is what", flush=True)
    print("     answers WHERE the colour lands: 2026-07-28's sweep-red showed RED DIGITS", flush=True)
    print("     on all eight and NO background fill anywhere, so the colour argument", flush=True)
    print("     colours the DIGITS -- including STYLE_COLOR, whose 'white BACKGROUND with", flush=True)
    print("     black digit cutouts' reading came from a label-contaminated probe and is", flush=True)
    print("     falsified. Do not reinstate it without a red-equivalent reproduction.", flush=True)
    print("  2. AFTER THE SWEEP: the panel is left on style 0, ordinary white face. That", flush=True)
    print("     final face is cleanup, NOT a ninth measurement.", flush=True)
    print("", flush=True)
    print("  REPORT AFTERWARDS -- two questions, and nothing else is needed:", flush=True)
    print("    (a) HOW MANY VISUALLY DISTINCT faces did you see in total?", flush=True)
    print("    (b) AT WHICH TRANSITIONS did the face change? Roughly is fine -- 'it", flush=True)
    print("        changed once, about a third of the way in' maps onto a style number", flush=True)
    print("        via the timestamps printed below as the run goes.", flush=True)
    print("  DO NOT try to time anything off the panel clock: this panel shows hours and", flush=True)
    print("  minutes only, with NO SECONDS. Just watch.", flush=True)
    print("=============================================================================", flush=True)


async def main(sequence: str) -> None:
    print(f"sequence: {sequence} -- {SEQUENCES[sequence]}", flush=True)
    print_visual_script("RED" if SEQUENCE_COLOURS[sequence] == RED else "WHITE")
    print("\nconnecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, SCREEN) as client:
        # NEVER cleared: each phase reports the slice since its own mark, so a
        # late reply shows up in a later phase instead of vanishing.
        acks: list[tuple[float, str]] = []
        unsubscribe = client.add_response_listener(lambda ack: acks.append((time.perf_counter(), repr(ack))))
        try:
            print("\n*** SWEEP STARTS NOW -- watch the panel continuously ***", flush=True)
            for index, (style, name) in enumerate(STYLES, start=1):
                mark = len(acks)
                wall = datetime.now()
                print(f"\n  [{index}/{len(STYLES)}]  {wall:%H:%M:%S}  style {style} -- {name}",
                      flush=True)
                sent_at = time.perf_counter()
                try:
                    await client.clock.show(style=style, color=SEQUENCE_COLOURS[sequence])
                except Exception as ex:
                    print(f"      SEND FAILED: {ex!r} (continuing -- the face on the panel is "
                          f"still the PREVIOUS style, note the gap)", flush=True)

                await asyncio.sleep(SETTLE_SECONDS)
                window = acks[mark:]
                if window:
                    print(f"      acks: {len(window)}", flush=True)
                    for at, text in window:
                        print(f"        {at - sent_at:+.2f}s after send  {text}", flush=True)
                else:
                    print(f"      acks: NONE within {SETTLE_SECONDS:.1f}s -- record it as silence, "
                          f"not as a failure; a later reply will appear under a later style",
                          flush=True)
                await asyncio.sleep(STYLE_SECONDS - SETTLE_SECONDS)

            print(f"\n  {datetime.now():%H:%M:%S}  sweep complete -- the LAST style shown was "
                  f"{STYLES[-1][0]} ({STYLES[-1][1]}).", flush=True)
        finally:
            print("\nleaving the panel on style 0, ordinary white face (cleanup, not a phase) ...",
                  flush=True)
            try:
                await client.clock.show(style=clock_protocol.STYLE_RGB_SWIPE_OUTLINE, color=WHITE)
            except Exception as ex:
                print(f"  cleanup clock.show FAILED: {ex!r}", flush=True)
            unsubscribe()

    print("\ndisconnected. Now answer: (a) how many DISTINCT faces, (b) at which transitions.",
          flush=True)


asyncio.run(main(select_sequence(sys.argv[1:])))
