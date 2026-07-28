"""P4-follow-up -- does a sustained GRAFFITI stream break the NEXT write?

WHY THIS PROBE EXISTS
---------------------
P4's `deltas` and `mix` phases (2026-07-28) both ended the same way: the very
first write after the streaming loop -- the cleanup clock command
`08 00 06 01 c0 ff ff ff` -- failed with `Unreachable`, and the transport had to
force a reconnect and retry. P4's `frames` phase, 900 full frames over ten
minutes with no graffiti at all, ended CLEANLY.

That points at graffiti traffic rather than at rate: the `mix` phase ran at only
11 sends/s total, far below the 40 cmd/s that the `deltas` phase sustained with
no misses at all. But it is two observations, both from cleanup code that P4
never instrumented, so it is a hypothesis and not a finding.

If it is real it matters more than the streaming envelope P4 was written to
measure: GlanceOS renders almost entirely through graffiti deltas, so "the next
non-graffiti write after a delta burst fails once" is a defect surface sitting
directly in the daemon's hot path.

WHAT IS HELD CONSTANT
---------------------
Both arms stream for the same duration at the same send rate and then issue the
SAME probe write (the clock command, byte-for-byte what P4's cleanup sent). The
only difference is what was streamed: full DIY frames, or graffiti deltas. The
arms alternate A/B/A/B so a drift over the run cannot masquerade as an effect.

The delta rate is deliberately 10 cmd/s -- a quarter of the 40 cmd/s that P4
proved clean. This probe is not a stress test; loading the link hard would
reintroduce the very confound it exists to remove.

HOW A FAILURE IS DETECTED, GIVEN THE TRANSPORT SELF-HEALS
---------------------------------------------------------
`BleTransport` catches this exact failure and retries once after a forced
reconnect, so the write usually SUCCEEDS from the caller's point of view and an
exception is the wrong thing to wait for. What gives it away is the repair:
`snapshot().reconnect_count` rises, and `snapshot().last_failure` carries the
message. Each probe write is therefore bracketed by snapshots, and a step is
scored FAILED if the reconnect count moved or a new `last_failure` appeared --
whether or not the call itself raised.

SEQUENCES
---------
  confirm      A/B/A/B: frames-then-write, deltas-then-write, twice each.
               Four 60 s streams, ~5 min total. Answers the hypothesis.
  discriminate After a delta stream, send a GRAFFITI write first and only then
               the clock write. If graffiti succeeds where the clock write
               fails, the link is fine and it is the MODE TRANSITION that
               breaks -- a much narrower and more useful finding than "the link
               dies". ~1.5 min.

SAFETY
------
Deltas go through `client.display.set_pixels`, the batching public API, with 255
coordinates per call -- never a raw graffiti frame, and never over
`graffiti.MAX_PIXELS_PER_COMMAND` (P13 phase E: 256 in one command crashes the
panel's BLE stack and needs a physical power cycle). No reset, no brightness,
no eco, no flip, no RTC write, no experimental namespace, and nothing anywhere
near the password or UART surface. The panel is left on the clock face.

NOTHING TO WATCH. Every result is captured in code and printed as a table.

USAGE
-----
    python probes/probe_p4b_post_stream_write.py confirm
    python probes/probe_p4b_post_stream_write.py discriminate

The argument is mandatory.

RESULT (2026-07-28): **NOT REPRODUCED. The hypothesis is dead as stated.**

A/B/A/B, four 60 s streams, gentle 10 cmd/s deltas and 1.5 fps frames:

    after frames #1   clock   0.17s   repaired=no   clean
    after deltas #1   clock   0.05s   repaired=no   clean
    after frames #2   clock   0.19s   repaired=no   clean
    after deltas #2   clock   0.04s   repaired=no   clean

    clock write FAILED after frames: 0/2
    clock write FAILED after deltas: 0/2

Zero failures in either arm. Graffiti traffic does NOT, by itself, break the
next write. Do not record "delta streaming breaks the next write" anywhere; it
was a two-observation hypothesis drawn from uninstrumented cleanup code, and it
did not survive a controlled test.

WHAT THIS RUN DID NOT REPLICATE, and why the P4 failures are still unexplained:

  * DURATION. P4's failing phases streamed for 300 s; each arm here ran 60 s.
  * ACCUMULATED STRESS. P4's `deltas` phase reached the probe write only after a
    60 cmd/s step that had already produced back-pressure -- 55.23/s achieved
    against a 60/s target, 143 missed pacing slots. This probe deliberately ran
    a quarter of the proven-clean rate throughout, to keep load out of the
    comparison. In hindsight that may have removed the actual cause along with
    the confound.

So the better hypothesis is accumulated stress or sustained duration, not
graffiti as a category -- which also fits `mix` failing at only 11 sends/s after
300 s. It was NOT chased further: the transport's retry-once-after-forced-
reconnect path handled it correctly on both P4 occasions, so this is the
self-heal working as designed, not a defect surface. Revisit only if a caller
ever reports a post-stream write that does NOT recover.

Method note for whoever revisits it: detecting this needs the snapshot bracket
used here (reconnect_count / last_failure), not a try/except -- the transport
repairs itself and the call returns success, so an exception never arrives.
"""

import asyncio
import sys
import time

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import graffiti

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32
W = H = 32

STREAM_SECONDS = 60.0
DELTA_RATE = 10.0  # a quarter of the proven-clean 40 cmd/s; this is not a stress test
FRAME_RATE = 1.5  # the rate P4 proved comfortable, 1.00 ack ratio over 10 min
SETTLE_SECONDS = 2.0

SEQUENCES = {
    "confirm": "A/B/A/B frames-then-write vs deltas-then-write, 4 x 60s, ~5 min",
    "discriminate": "after a delta stream, graffiti write BEFORE the clock write, ~1.5 min",
}


def print_usage() -> None:
    print("usage: python probes/probe_p4b_post_stream_write.py <sequence>", flush=True)
    print("", flush=True)
    print("Runs exactly ONE sequence. The argument is mandatory.", flush=True)
    for key, description in SEQUENCES.items():
        print(f"    {key:13s} {description}", flush=True)


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


def a_frame(tick: int) -> bytes:
    """A cheap full frame that changes every tick, so nothing can be deduped.

    show_frame wants FLAT RGB bytes -- width*height*3 -- not a list of pixel
    tuples. Getting that wrong is how the first run of this probe died.
    """
    shade = (tick * 7) % 200 + 30  # 30..229, so 230 - shade stays 1..200
    return bytes([shade, 40, 230 - shade] * (W * H))


def a_delta_batch(tick: int) -> list[tuple[int, int]]:
    """Exactly 255 coordinates -- the documented maximum, never more."""
    start = (tick * 255) % (W * H)
    return [((start + i) % (W * H) % W, (start + i) % (W * H) // W) for i in range(255)]


async def stream(client: IDotMatrixClient, kind: str, seconds: float) -> int:
    """Streams `kind` for `seconds` at its rate. Returns how many sends landed."""
    rate = FRAME_RATE if kind == "frames" else DELTA_RATE
    interval = 1.0 / rate
    deadline = time.monotonic() + seconds
    sent = 0
    while time.monotonic() < deadline:
        due = time.monotonic() + interval
        if kind == "frames":
            await client.display.show_frame(a_frame(sent), wait_for_device=False)
        else:
            await client.display.set_pixels((0, 200, 255), a_delta_batch(sent))
        sent += 1
        nap = due - time.monotonic()
        if nap > 0:
            await asyncio.sleep(nap)
    return sent


async def probe_write(client: IDotMatrixClient, label: str, kind: str) -> dict:
    """Issues one write and reports whether the transport had to repair itself.

    The transport retries once after a forced reconnect, so the call usually
    succeeds; the repair is the evidence, not an exception.
    """
    before = client.snapshot()
    raised: str | None = None
    started = time.monotonic()
    try:
        if kind == "clock":
            await client.clock.show()
        else:
            await client.display.set_pixels((255, 80, 0), a_delta_batch(0))
    except Exception as exc:  # noqa: BLE001 -- recording it IS the measurement
        raised = repr(exc)
    elapsed = time.monotonic() - started
    await asyncio.sleep(SETTLE_SECONDS)
    after = client.snapshot()

    healed = after.reconnect_count > before.reconnect_count
    new_failure = after.last_failure if after.last_failure_at != before.last_failure_at else None
    return {
        "label": label,
        "write": kind,
        "seconds": elapsed,
        "raised": raised,
        "healed": healed,
        "failure": new_failure,
        "failed": bool(healed or new_failure or raised),
    }


def print_table(rows: list[dict]) -> None:
    print("\n=== P4b SUMMARY ============================================================", flush=True)
    print(f"  {'step':28s} {'write':9s} {'took':>7s}  {'repaired':8s} {'VERDICT':7s}", flush=True)
    for row in rows:
        verdict = "FAILED" if row["failed"] else "clean"
        print(
            f"  {row['label']:28s} {row['write']:9s} {row['seconds']:6.2f}s  "
            f"{'yes' if row['healed'] else 'no':8s} {verdict:7s}",
            flush=True,
        )
        if row["failure"]:
            print(f"      transport reported: {row['failure']}", flush=True)
        if row["raised"]:
            print(f"      call raised: {row['raised']}", flush=True)
    print("  'repaired' = the transport forced a reconnect and retried, i.e. the write", flush=True)
    print("  failed even though the call may have returned successfully.", flush=True)

    after_frames = [r for r in rows if r["label"].startswith("after frames")]
    after_deltas = [r for r in rows if r["label"].startswith("after deltas") and r["write"] == "clock"]
    if after_frames and after_deltas:
        ff = sum(r["failed"] for r in after_frames)
        df = sum(r["failed"] for r in after_deltas)
        print("", flush=True)
        print(f"  clock write FAILED after frames: {ff}/{len(after_frames)}", flush=True)
        print(f"  clock write FAILED after deltas: {df}/{len(after_deltas)}", flush=True)
        if df and not ff:
            print("  => CONFIRMED: graffiti streaming breaks the next write; full frames do not.", flush=True)
        elif df and ff:
            print("  => NOT graffiti-specific: both arms failed. Streaming itself is the variable.", flush=True)
        elif not df:
            print("  => NOT REPRODUCED this run. P4's cleanup failures need another explanation.", flush=True)
    print("============================================================================", flush=True)


async def main(sequence: str) -> None:
    print(f"sequence: {sequence} -- {SEQUENCES[sequence]}", flush=True)
    print("", flush=True)
    print("NOTHING TO WATCH. The panel shows a shifting field while streaming; it is", flush=True)
    print("not a measurement. Every result is captured in code. You can leave.", flush=True)
    print("", flush=True)
    print(f"max pixels per graffiti command this run: 255 "
          f"(limit {graffiti.MAX_PIXELS_PER_COMMAND})", flush=True)

    rows: list[dict] = []
    print("connecting ...", flush=True)
    try:
        async with IDotMatrixClient.connect_to(ADDRESS, SCREEN) as client:
            if sequence == "confirm":
                for trial in (1, 2):
                    for kind in ("frames", "deltas"):
                        print(f"\n--- streaming {kind} for {STREAM_SECONDS:.0f}s "
                              f"(trial {trial}) ---", flush=True)
                        sent = await stream(client, kind, STREAM_SECONDS)
                        print(f"    {sent} sends; now the probe write", flush=True)
                        rows.append(await probe_write(client, f"after {kind} #{trial}", "clock"))
            else:
                print(f"\n--- streaming deltas for {STREAM_SECONDS:.0f}s ---", flush=True)
                sent = await stream(client, "deltas", STREAM_SECONDS)
                print(f"    {sent} sends; graffiti write FIRST, then the clock write", flush=True)
                rows.append(await probe_write(client, "after deltas (graffiti)", "graffiti"))
                rows.append(await probe_write(client, "after deltas (clock)", "clock"))

            print("\n--- cleanup ---", flush=True)
            try:
                await client.clock.show()
                print("panel restored to the clock face.", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"cleanup clock.show failed: {exc!r}", flush=True)
    finally:
        if rows:
            print_table(rows)


asyncio.run(main(select_sequence(sys.argv[1:])))
