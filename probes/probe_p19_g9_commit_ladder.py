"""P19 G9 -- condition (A)'s COMMIT time, measured by power cycle.

WHY THIS PROBE EXISTS
---------------------
The 2026-07-28 (A) ladder (probe_p19_g5_kill_event.py `own-delayed`) bracketed a
threshold at 100 s < t <= 180 s -- but every rung asked its question with a
RECONNECT. A reconnect can only read the ACTIVE MODE. Only a power cycle reads
FLASH, and G7/G8 established those are different states.

G8's `no-arm` control showed the two are not trivially the same question: an
8-second-old unassisted write did NOT reach flash. That is the only point on the
commit curve measured by the correct instrument. Everything above 8 s is unknown,
and the reconnect-measured 100-180 s bracket may or may not coincide with it.

This probe walks the same ladder with a power cycle as the readout.

ONE TRIAL PER INVOCATION, and the colour identifies it
------------------------------------------------------
Each trial takes an explicit COLOUR as well as a dwell, and every trial must use
a colour the current flash state is NOT. Reusing a colour already in flash makes
"committed" and "reverted" the same picture -- the confound that invalidated two
dwell trials on 2026-07-28 and cost hours.

Because each trial's colour is unique, the BOOT COLOUR NAMES THE TRIAL THAT
COMMITTED. If a 60 s trial writes cyan and the panel boots cyan, 60 s was
enough; if it boots the previous trial's colour, it was not. No bookkeeping
beyond writing down which colour went with which dwell.

There is deliberately NO reconnect anywhere in this probe: a reconnect would arm
the commit (condition B, see G8) and destroy the measurement.

WHAT THE OPERATOR DOES
----------------------
  1. Confirm the stated colour appears.
  2. After the probe exits, PULL THE PANEL'S POWER, plug it back in, and report
     the BOOT colour. That reading is the entire measurement.

The probe cannot power-cycle the panel and does not wait for it.

SAFETY
------
One fullscreen colour per run. No reset, no brightness, no eco, no flip, no RTC
write, no GIF, no graffiti, no experimental namespace, nothing near the password
or UART surface. The panel is deliberately LEFT on the trial colour -- restoring
would overwrite the state being measured.

USAGE
-----
    python probes/probe_p19_g9_commit_ladder.py <seconds> <colour>

    e.g. python probes/probe_p19_g9_commit_ladder.py 60 cyan

Colours: see PALETTE below. Runtime = dwell + ~15 s, plus your power cycle.

RESULT (2026-07-28): **the unassisted flash commit is 8 s < t <= 15 s -- an
order of magnitude faster than the reconnect-measured ladder, because the two
ladders measure DIFFERENT THINGS.**

Ladder, each rung a fresh session with NO reconnect, read by power cycle:

    dwell   colour    booted     commits?
      8 s   magenta   blue       NO   (G8 `no-arm`, the lower anchor)
     15 s   red       RED        YES
     30 s   yellow    YELLOW     YES
     60 s   cyan      CYAN       YES

Each trial wrote a colour the current flash state was not, so the boot colour
names the trial that committed and no reading was a judgement call.

WHAT THIS CORRECTS. The (A) figure recorded from probe_p19_g5_kill_event.py's
ladder -- 100 s < t <= 180 s -- was measured with a RECONNECT, and a reconnect
can only read the ACTIVE MODE. It is a DISPLAY-MODE TAKEOVER time, not a commit
time. The commit itself, read straight from flash by power-cycling, happens
inside 15 s. Both numbers are real; they answer different questions:

    "will this survive a power cut?"   -> commit:   <= 15 s unassisted,
                                                    <= 8 s after a reconnect (G8)
    "will this survive a reconnect?"   -> takeover: 100-180 s unassisted

A caller who wants durability across a power cut needs far less patience than
the 3-minute figure the docs were about to publish; a caller who wants their
content to survive the next BLE reconnect needs the longer one, or condition (B).

NOT NARROWED FURTHER on purpose: the band is 7 s wide and the guidance ("a write
is durable within about fifteen seconds") does not change anywhere inside it.

CREDIT WHERE DUE: the operator predicted this outright -- "lazy time will be
much lower" -- before any of it was measured. The reason it took a new probe is
that G8's `no-arm` had tested only 8 s, which sits just below the threshold and
so looked like confirmation that the unassisted commit was slow.
"""

import asyncio
import sys

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

# Deliberately far apart, and none of them close to the blue/green/orange this
# series has already used, so a boot reading is never a judgement call.
PALETTE: dict[str, tuple[int, int, int]] = {
    "magenta": (255, 0, 200),
    "cyan": (0, 220, 220),
    "yellow": (255, 200, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "lime": (120, 255, 0),
}

DWELL_MIN, DWELL_MAX = 5.0, 600.0
WATCH_SECONDS = 8.0
SETTLE_SECONDS = 2.0


def print_usage() -> None:
    print("usage: python probes/probe_p19_g9_commit_ladder.py <seconds> <colour>", flush=True)
    print("", flush=True)
    print(f"seconds: {DWELL_MIN:.0f}..{DWELL_MAX:.0f}, how long the colour is held before", flush=True)
    print("         the link drops. NO reconnect happens -- that would arm the commit.", flush=True)
    print(f"colour : {', '.join(PALETTE)}", flush=True)
    print("", flush=True)
    print("Use a colour the panel's CURRENT flash state is not, and a different one", flush=True)
    print("each trial -- the boot colour is what tells you which trial committed.", flush=True)


def select(argv: list[str]) -> tuple[float, str]:
    """Validated before any BLE contact, so a typo cannot burn a panel session."""
    if len(argv) != 2:
        print(f"error: expected exactly 2 arguments, got {len(argv)}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    try:
        dwell = float(argv[0])
    except ValueError:
        print(f"error: seconds must be a number, got {argv[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2) from None
    if not DWELL_MIN <= dwell <= DWELL_MAX:
        print(f"error: seconds must be {DWELL_MIN:.0f}..{DWELL_MAX:.0f}, got {dwell:g}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    colour = argv[1].lower()
    if colour not in PALETTE:
        print(f"error: unknown colour {argv[1]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    return dwell, colour


def print_visual_script(dwell: float, colour: str) -> None:
    """EVERY visual of the run, in order, printed before any BLE contact."""
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER ============================================", flush=True)
    print("  0. BEFORE: whatever is on the panel now. Not a measurement.", flush=True)
    print(f"  1. {colour.upper()} fills the panel and is held {dwell:.0f}s.", flush=True)
    print("     NO reconnect happens at any point -- a reconnect would ARM the commit", flush=True)
    print("     (condition B, see G8) and there would be nothing left to measure.", flush=True)
    print("  2. The link drops and the probe EXITS, leaving the panel as it is.", flush=True)
    print("     Nothing is restored: restoring would overwrite the measurement.", flush=True)
    print("  3. YOU: pull the panel's power, plug it back in, report the BOOT colour.", flush=True)
    print(f"       BOOTS {colour.upper():8s} -> {dwell:.0f}s IS enough to commit unassisted.", flush=True)
    print("       BOOTS SOMETHING ELSE -> it is not; that colour is an earlier trial's,", flush=True)
    print("           and it names the last dwell that DID commit.", flush=True)
    print("============================================================================", flush=True)
    print("", flush=True)


async def main(dwell: float, colour: str) -> None:
    rgb = PALETTE[colour]
    print(f"trial: {dwell:.0f}s dwell, colour {colour.upper()} {rgb}", flush=True)
    print_visual_script(dwell, colour)

    print("connecting ...", flush=True)
    client = IDotMatrixClient(SCREEN, mac_address=ADDRESS)
    await client.connect()
    try:
        snapshot = client.snapshot()
        print(f"  transport: {snapshot}", flush=True)
        print(f"\n=== writing {colour.upper()}, holding {dwell:.0f}s (no reconnect) ===", flush=True)
        await client.color.show(rgb)
        await asyncio.sleep(SETTLE_SECONDS)
        print(f"    confirm the panel is {colour.upper()}.", flush=True)
        await asyncio.sleep(max(0.0, dwell - SETTLE_SECONDS))
    finally:
        await client.disconnect()

    await asyncio.sleep(WATCH_SECONDS)
    print("\n=== NOW: POWER-CYCLE THE PANEL and report the BOOT colour.", flush=True)
    print(f"    BOOTS {colour.upper()} -> {dwell:.0f}s commits unassisted.", flush=True)
    print(f"    BOOTS ANYTHING ELSE -> {dwell:.0f}s does not; the boot colour names the", flush=True)
    print("        last trial that did.", flush=True)
    print("(panel left as-is deliberately -- restoring would overwrite the measurement)", flush=True)


asyncio.run(main(*select(sys.argv[1:])))
