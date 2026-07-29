"""P19 G5 -- what makes a display write survive a disconnect/reconnect?

WHY THIS PROBE EXISTS
---------------------
This probe was written under a model that IT THEN FALSIFIED, so read the
docstring as it now stands and not as an argument for that model.

The model under test was "the first-connection shadow": display state set on a
client session's FIRST BLE connection is non-durable, and the effect is
SESSION-BOUND -- only the session that wrote the content can lose it. Every run
in the series was consistent with it, but every run was ALSO consistent with a
much duller explanation the lab had already recorded on 2026-07-12/17: the
panel commits its display mode to flash LAZILY, and a clean disconnect reverts
it to the last PERSISTED mode. The two models were never separated because the
runs that died reconnected ~8 s after writing, while the runs that survived all
had MINUTES of elapsed time (the operator typing between commands). Session
identity and elapsed time were confounded throughout.

WHAT THE TWO SEQUENCES DO
-------------------------
`reconnect` was the original probe: it attaches to content ANOTHER process left
on the panel and performs one disconnect/reconnect of its own. Under the
session-bound model, content dying here would have meant the reset was
universal; content surviving would have meant it was session-bound.

`own-delayed` is the sequence that settled it. The SAME session writes the
content, HOLDS a chosen dwell with the link up and nothing sent, then reconnects
-- session identity held constant, dwell the only variable against the known
8-second result.

RESULT (2026-07-28): `reconnect` SURVIVED, and `own-delayed` run as a LADDER
brackets the dwell threshold at 100 s < t <= 180 s.

`reconnect` surviving is what the session-bound model predicted -- but that run
also had minutes of dwell behind it, so it discriminates nothing. The ladder is
what the session-bound model FORBADE: at 180 s the writing session could not
kill its own content. ELAPSED TIME IS THE VARIABLE, NOT OWNERSHIP. The
session-bound model is RETRACTED, and with it the per-client-session claim that
had been recorded in capabilities.py and docs/PROBE_PLAN.md.

THE LADDER, one trial per invocation:

    8 s DIED   30 s DIED   60 s DIED   75 s DIED   90 s DIED   100 s DIED
    180 s SURVIVED

So the threshold is 100 s < t <= 180 s, which CONFIRMS this lab's 2026-07-12
record ("dwell somewhere under ~3 min"). It is not narrowed further on purpose:
a valid isolated trial costs ~6 min (see the protocol rule below) and the
guidance -- allow ~3 minutes, or reconnect once first -- does not change
anywhere inside that band.

TWO RUNS RETRACTED -- do not count them as evidence in either direction:

  * `own-delayed 140` (reported SURVIVED) ran straight after the 180 s trial, so
    ORANGE WAS ALREADY THE FLASH STATE. Reversion and survival were the same
    picture.
  * the `own-delayed 60` RERUN (reported SURVIVED) had the same confound,
    compounded: a noise GIF was activated as a decoy but had only ~10 s, nowhere
    near a commit, so flash still held orange underneath.

The earlier "90 s SURVIVED" reading -- the one that first sent the model astray
-- is WITHDRAWN for exactly the same reason: it wrote orange while orange was
already displayed. The ladder's 90 s point, run under a valid discriminator,
DIED.

PROTOCOL RULE, learned the hard way twice and the reason the ladder is trusted
where those runs are not: to ask "did this write survive?", the PERSISTED state
must differ from what is being written -- not merely the ACTIVE one -- and
establishing that costs a full commit period of its own. Making a decoy VISIBLE
is not the same as making it COMMITTED.

The corrected model has TWO independent sufficient conditions, and content
survives if either holds:

  (A) DWELL, in a session with no prior reconnect -- 100 s < t <= 180 s, per the
      ladder above.
  (B) A PRIOR DISCONNECT/RECONNECT earlier in the same session --
      `--preamble ble gif` survives at ~8 s where the matched control dies
      (reproduced twice), and probe_p19_g7_isolated_dwell.py then showed
      fullscreen colour surviving at 10 s the same way. ~10 s of (B) beats 100 s
      of (A). Dwell cannot explain it and its MECHANISM IS OPEN. This probe does
      not test it -- see G7.

Full account in capabilities.py's display.persistence_matrix and in
probe_p11_persistence.py's module docstring.

PRECONDITION for `reconnect` -- the run is void without it
----------------------------------------------------------
Something DISTINCTIVE and NON-CLOCK must already be on the panel, put there by
an earlier process. The intended setup is the state left by:

    python probes/probe_p11_persistence.py set <row>

optionally followed by a physical power cycle. The operator is asked to confirm
what is up BEFORE the reconnect, so a run that starts on an ordinary clock face
can be discarded rather than misread -- a clock that "survives" proves nothing,
because a clock is also what a reset looks like. NOTE the dwell confound this
sequence cannot escape: `set` runs in its own process and the operator's own
elapsed time before starting this one is uncontrolled, which is precisely why
`own-delayed` had to exist.

ACK DISCIPLINE
--------------
`reconnect` sends nothing, so there is nothing to ack. `own-delayed` sends one
colour command. The transport snapshot is printed around each reconnect purely
so a failed reconnect cannot be mistaken for a content change.

SAFETY
------
`reconnect` sends no commands at all and leaves the panel exactly as found;
`own-delayed` sends one fullscreen colour and leaves it up. Neither touches
reset, brightness, eco, flip, the RTC, the experimental namespace, or the
password / UART surface. Run `probe_p11_persistence.py restore` afterwards to
clean up.

USAGE
-----
    python probes/probe_p19_g5_kill_event.py reconnect
    python probes/probe_p19_g5_kill_event.py own-delayed [seconds]

The sequence argument is mandatory. `own-delayed` takes an optional dwell in
seconds (5..300, default 90) -- the knob the ladder above was run on. The
threshold is now bracketed (100 s < t <= 180 s) and further bisection is NOT
wanted, so this argument exists for re-checks, not for more ladder rungs.

ONE TRIAL PER INVOCATION, and that is not a style choice: this probe's own
disconnect/reconnect satisfies condition (B) for everything afterwards, so a
second trial in the same process would be rescued by the first and measure
nothing. Each dwell needs a fresh run.

Runtime ~35 s / dwell + ~25 s.
"""

import asyncio
import sys

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

BLE_GAP_SECONDS = 6.0  # the gap every rescuing/killing run in this lab has used
WATCH_SECONDS = 8.0
SETTLE_SECONDS = 2.0

OWN_SESSION_DELAY_SECONDS = 90.0

SEQUENCES = {
    "reconnect": "attach to existing content, one disconnect/reconnect, ask if it survived",
    "own-delayed": (f"set colour, WAIT {OWN_SESSION_DELAY_SECONDS:.0f}s, then the SAME session reconnects"),
}


def print_usage() -> None:
    print("usage: python probes/probe_p19_g5_kill_event.py <sequence> [seconds]", flush=True)
    print("", flush=True)
    print("Runs exactly ONE sequence. The sequence argument is mandatory.", flush=True)
    print(
        f"own-delayed takes an optional dwell in seconds "
        f"({DWELL_MIN_SECONDS:.0f}..{DWELL_MAX_SECONDS:.0f}, "
        f"default {OWN_SESSION_DELAY_SECONDS:.0f}).",
        flush=True,
    )
    for key, description in SEQUENCES.items():
        print(f"    {key:10s} {description}", flush=True)


DWELL_MIN_SECONDS = 5.0
DWELL_MAX_SECONDS = 300.0


def select_sequence(argv: list[str]) -> tuple[str, float]:
    """Validated before any BLE contact, so a typo cannot burn a panel session.

    Returns the sequence and the dwell to use. `own-delayed` accepts an optional
    seconds override so the threshold can be bisected one trial per invocation --
    ONE trial is all a process can give, because this probe's own reconnect
    satisfies condition (B) for everything afterwards.
    """
    if not argv:
        print("error: a sequence name is required.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    if argv[0] not in SEQUENCES:
        print(f"error: unrecognized sequence {argv[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    sequence = argv[0]
    rest = argv[1:]

    if not rest:
        return sequence, OWN_SESSION_DELAY_SECONDS
    if sequence != "own-delayed":
        print(f"error: {sequence} takes no extra arguments.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    if len(rest) > 1:
        print(f"error: expected at most one dwell value, got {len(rest)}.\n", flush=True)
        print_usage()
        raise SystemExit(2)
    try:
        dwell = float(rest[0])
    except ValueError:
        print(f"error: dwell must be a number of seconds, got {rest[0]!r}.\n", flush=True)
        print_usage()
        raise SystemExit(2) from None
    if not DWELL_MIN_SECONDS <= dwell <= DWELL_MAX_SECONDS:
        print(
            f"error: dwell must be between {DWELL_MIN_SECONDS:.0f} and "
            f"{DWELL_MAX_SECONDS:.0f} seconds, got {dwell:g}.\n",
            flush=True,
        )
        print_usage()
        raise SystemExit(2)
    return sequence, dwell


def print_visual_script() -> None:
    """EVERY visual of the run, in order, printed before any BLE contact."""
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER ============================================", flush=True)
    print("  0. NOTHING IS SENT AT ANY POINT IN THIS RUN. Whatever is on the panel now", flush=True)
    print("     stays there on its own. This probe only connects, drops the link, and", flush=True)
    print("     reconnects.", flush=True)
    print("  1. BEFORE (8s): the panel keeps showing whatever it already showed.", flush=True)
    print("     CONFIRM IT IS DISTINCTIVE AND NOT A PLAIN CLOCK. If it is an ordinary", flush=True)
    print("     clock face, say so and discard the run -- a clock cannot be seen to", flush=True)
    print("     'survive', because a clock is also exactly what a reset looks like.", flush=True)
    print("  2. A ~6s GAP with the link down. Nothing is sent during it.", flush=True)
    print("  3. AFTER RECONNECT (8s): THE QUESTION. Is the content from step 1 still", flush=True)
    print("     there, or did the clock take over?", flush=True)
    print("       SURVIVED -> the content had already been PERSISTED before this run", flush=True)
    print("                   started, so a foreign reconnect cannot dislodge it.", flush=True)
    print("       CLOCK    -> the revert is universal: ANY client's reconnect drops a", flush=True)
    print("                   not-yet-persisted display mode, whoever wrote it.", flush=True)
    print("     CAVEAT: this sequence cannot control how long the content has already", flush=True)
    print("     dwelt, so SURVIVED here is weak evidence. `own-delayed` is the run that", flush=True)
    print("     actually separates dwell from session identity.", flush=True)
    print("  4. The panel is left exactly as the run found it. Nothing is restored,", flush=True)
    print("     because restoring would mean sending something.", flush=True)
    print("============================================================================", flush=True)
    print("", flush=True)


async def run_own_delayed(dwell: float) -> None:
    """Separates SESSION IDENTITY from ELAPSED TIME -- the last confound.

    Every run where content DIED reconnected ~6-8s after writing it. Every run
    where content SURVIVED a foreign session's reconnect had minutes of elapsed
    time first (the operator typing between commands). So "only the writing
    session can kill it" and "a write is provisional for a while, then commits"
    predicted the identical outcome in every run up to this one.

    This is the same session that wrote the content, so session identity is held
    constant and only the delay changes. Against the known 6s-gap result:
      SURVIVES -> elapsed time is the variable; writes commit after a while, and
                  the session-bound reading is wrong.
      DIES     -> session identity is the variable; the writing session can kill
                  its own content no matter how long it waits.

    RAN 2026-07-28 as a LADDER: 8/30/60/75/90/100 s DIED, 180 s SURVIVED. Elapsed
    time is the variable. The 180 s point is what retracted the session-bound
    model -- the writing session could not kill its own 180-second-old content.
    Two runs from that night (`140`, and the `60` rerun) are RETRACTED as
    flash-confounded, as is the original "90 s survived" reading; see the module
    docstring for the retractions and the protocol rule they taught.
    """
    print("", flush=True)
    print("=== WHAT YOU WILL SEE, IN ORDER ============================================", flush=True)
    print("  1. ORANGE (flat, whole panel) -- written by THIS session, which is also", flush=True)
    print("     the session that will reconnect. Session identity is held constant.", flush=True)
    print(f"  2. ORANGE HELD for {dwell:.0f}s with the link UP and NOTHING sent.", flush=True)
    print("     Nothing to watch; the wait IS the experiment -- the only variable.", flush=True)
    print("  3. A ~6s GAP with the link down.", flush=True)
    print("  4. AFTER RECONNECT (8s): THE QUESTION -- orange still there, or clock?", flush=True)
    print("       ORANGE -> DWELL is the variable; a write commits to flash with age,", flush=True)
    print("                 and the session-bound reading is wrong.", flush=True)
    print("       CLOCK  -> session identity is the variable; the delay changes nothing.", flush=True)
    print("     VOID IF ORANGE WAS ALREADY THE PERSISTED STATE -- e.g. a previous run", flush=True)
    print("     of this probe committed orange. Then reversion and survival look the", flush=True)
    print("     same and the trial says nothing. Two runs were lost this way.", flush=True)
    print("  5. The panel is left as the run ends it. Nothing is restored.", flush=True)
    print("============================================================================", flush=True)
    print("", flush=True)

    print("connecting (this session WRITES the content and later reconnects) ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, SCREEN) as client:
        await client.color.show((255, 120, 0))
        await asyncio.sleep(SETTLE_SECONDS)
        print("  ORANGE written. Confirm the panel is flat orange.", flush=True)

        print(f"\n=== HOLDING {dwell:.0f}s -- link up, nothing sent", flush=True)
        await asyncio.sleep(dwell)

        print(f"\n=== disconnect, {BLE_GAP_SECONDS:.0f}s down, reconnect (SAME session)", flush=True)
        await client.disconnect()
        await asyncio.sleep(BLE_GAP_SECONDS)
        await client.connect()
        await asyncio.sleep(SETTLE_SECONDS)
        snapshot = client.snapshot()
        print(f"  transport: {snapshot}", flush=True)
        if not snapshot.is_connected:
            print("  RECONNECT FAILED -- the run is void; nothing can be concluded.", flush=True)
            return

        print(f"\n=== AFTER RECONNECT -- watch for {WATCH_SECONDS:.0f}s", flush=True)
        print("    ORANGE -- DWELL is the variable; writes commit to flash with age.", flush=True)
        print("    CLOCK  -- session identity is the variable; the wait changed nothing.", flush=True)
        await asyncio.sleep(WATCH_SECONDS)

    print("\ndisconnected.", flush=True)


async def main(sequence: str, dwell: float) -> None:
    suffix = f"  [dwell {dwell:.0f}s]" if sequence == "own-delayed" else ""
    print(f"sequence: {sequence} -- {SEQUENCES[sequence]}{suffix}", flush=True)
    if sequence == "own-delayed":
        await run_own_delayed(dwell)
        return
    print_visual_script()

    print("connecting (this process has set NOTHING and will set nothing) ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, SCREEN) as client:
        print(f"  transport: {client.snapshot()}", flush=True)
        print(f"\n=== STEP 1: BEFORE -- watch for {WATCH_SECONDS:.0f}s", flush=True)
        print("  Confirm what is up, and that it is NOT a plain clock face.", flush=True)
        await asyncio.sleep(WATCH_SECONDS)

        print(f"\n=== STEP 2: disconnect, {BLE_GAP_SECONDS:.0f}s down, reconnect", flush=True)
        await client.disconnect()
        await asyncio.sleep(BLE_GAP_SECONDS)
        await client.connect()
        await asyncio.sleep(SETTLE_SECONDS)
        snapshot = client.snapshot()
        print(f"  transport: {snapshot}", flush=True)
        if not snapshot.is_connected:
            print("  RECONNECT FAILED -- the run is void; nothing can be concluded.", flush=True)
            return

        print(f"\n=== STEP 3: AFTER RECONNECT -- watch for {WATCH_SECONDS:.0f}s", flush=True)
        print("  Is the step 1 content still there?", flush=True)
        print("    SURVIVED -- it was already persisted; a foreign reconnect cannot", flush=True)
        print("                dislodge it. Weak evidence: dwell is uncontrolled here.", flush=True)
        print("    CLOCK    -- the revert is universal: any client's reconnect drops a", flush=True)
        print("                display mode the device has not persisted yet.", flush=True)
        await asyncio.sleep(WATCH_SECONDS)

    print("\ndisconnected. Panel left exactly as found -- nothing was ever sent.", flush=True)


asyncio.run(main(*select_sequence(sys.argv[1:])))
