"""P2-follow-up -- what does a GIF upload's TERMINAL StatusAck actually mean?

WHY THIS PROBE EXISTS
---------------------
The GIF upload handshake paces on `(0x01, 0x00)` StatusAcks: status 1 =
NEXT_CHUNK, and the transfer ends on a terminal status. The tidy reading has
been "terminal 0 = stored fresh, terminal 3 = recognized duplicate" -- but
`probes/probe_gif_chunk1_isolation.py` (2026-07-25) recorded it as SUSPECT:

    the prior night's cold seed-100 ended terminal 0; tonight's cold seed-102
    ended terminal 3, near-identical scenarios.

Two cold uploads of never-before-seen GIFs, ending in different terminal
statuses. Either the mapping is wrong, or something else varies between runs.
That probe asked for exactly what this one does: a terminal-status DISTRIBUTION
over repeated uploads, rather than another single anecdote.

This matters beyond tidiness. `_send_gif_upload` treats the terminal status as
the success signal, and `_send_chunked_upload` raises unless it sees SAVED --
so what these codes mean is load-bearing for whether a failed transfer is
detected or silently accepted.

THE TWO SEQUENCES
-----------------
  fresh      Five COLD uploads, each a different random seed the device has
             never held. If "0 = fresh" is right, all five end 0. Any mixture
             falsifies the mapping outright, and the distribution is the
             result -- not whichever value happens to come up first.
  duplicate  One cold upload, then the SAME BYTES again immediately. If
             "3 = duplicate" is right, the first ends 0 and the second ends 3.
             This is the only pairing where the two hypotheses make different
             predictions on consecutive commands, with nothing else varying.

Both print a table of terminal statuses. The distribution IS the finding; a
single run of either proves very little, which is the whole point.

WHAT THE OPERATOR HAS TO DO
---------------------------
Almost nothing. Every result is a status code captured in code. The panel plays
noise animations throughout; they are not measurements. The one thing worth
confirming is that the panel is still playing something at the end rather than
sitting on a clock face, which would suggest an upload silently failed to take.

ACK DISCIPLINE
--------------
Uploads are driven through the public `gif.upload_bytes`, which paces on the
handshake internally; the terminal status is read from a response listener that
records EVERY `(0x01, 0x00)` StatusAck with its arrival time. The listener is
never cleared between uploads -- each upload reports only the slice that
arrived after its own mark, so a late ack lands in a later upload's slice
rather than being destroyed. That is the bug that voided
`probe_effect_length_byte2.py`'s headline finding.

SAFETY
------
Uploads GIFs and shows the clock. No reset, no brightness, no eco, no flip, no
RTC write, no graffiti, no experimental namespace, nothing near the password or
UART surface. Fixtures are 32 frames of 32x32 noise (~45 KB), the same
generator the earlier P2 probes used.

USAGE
-----
    python probes/probe_p2b_terminal_status.py fresh
    python probes/probe_p2b_terminal_status.py duplicate

The argument is mandatory. Runtime ~2 min / ~1 min.

RESULT (2026-07-28): **terminal 3 for EVERY successful upload, fresh or
duplicate. The "0 = fresh store / 3 = duplicate" mapping is dead, and the real
duplicate discriminator is the ACK COUNT, not the terminal value.**

`duplicate` sequence:
    cold seed-216   11 acks in 8.27s   [1 x10, 3]   TERMINAL=3
    SAME seed-216    1 ack  in 1.18s   [3]          TERMINAL=3

`fresh` sequence, five never-before-uploaded seeds:
    cold seed-211   12 acks   TERMINAL=3
    cold seed-212   11 acks   TERMINAL=3
    cold seed-213   11 acks   TERMINAL=3
    cold seed-214   11 acks   TERMINAL=3
    cold seed-215   12 acks   TERMINAL=3

Seven uploads across two runs, every one terminal 3. This CORROBORATES the
correction already carried in capabilities.py's gif.upload_file entry -- that
the old terminal-0-means-fresh-store reading was a misread of silent failures --
and replaces the single anecdote that prompted it with a distribution.

WHAT ACTUALLY DISTINGUISHES A DUPLICATE, and it is not the terminal status:

    fresh      11-12 StatusAcks, ~8.3-8.7 s  (the full chunk handshake runs)
    duplicate   1 StatusAck,      ~1.2 s     (single-slot CRC hit, no chunking)

An order of magnitude apart in both. A caller wanting to know whether the device
already held the payload should look at whether the handshake ran at all -- which
is exactly what gif.activate_stored() exposes -- and never at the terminal code,
which is 3 either way.

So the vocabulary is simply uniform with Timer/Schedule: 1 = NEXT_CHUNK,
3 = SAVED, 0 = FAILED. Terminal 3 means SAVED and carries no information about
novelty.

ON THE ONE OBSERVED TERMINAL 0 (cold seed-100, 2026-07-24): against seven 3s it
is an outlier, and under the unified vocabulary it reads as a genuine FAILED --
not a "fresh store" variant. Note the driver now RAISES UploadError on anything
that is not SAVED, so a repeat would surface loudly rather than silently. It was
NOT reproduced here and needs no further chasing unless it recurs.

Incidental: ack counts vary 11 vs 12 for same-generator fixtures, i.e. chunk
count tracks the compressed GIF size, which differs slightly by seed. Not a
finding, just why the column is not constant.
"""

import asyncio
import io
import random
import sys
import time

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize

ADDRESS = "6D:FD:F8:A0:3E:AF"
SCREEN = ScreenSize.SIZE_32x32

FRESH_SEEDS = (211, 212, 213, 214, 215)  # never uploaded before this probe
DUPLICATE_SEED = 216
SETTLE_SECONDS = 3.0

SEQUENCES = {
    "fresh": "five COLD uploads of distinct never-seen GIFs -- tests '0 = fresh store'",
    "duplicate": "one cold upload then the SAME bytes again -- tests '3 = duplicate'",
}


def print_usage() -> None:
    print("usage: python probes/probe_p2b_terminal_status.py <sequence>", flush=True)
    print("", flush=True)
    print("Runs exactly ONE sequence. The argument is mandatory.", flush=True)
    for key, description in SEQUENCES.items():
        print(f"    {key:10s} {description}", flush=True)


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


def make_big_gif(seed: int) -> bytes:
    """Byte-identical to probe_gif_crc_cache3.py / probe_gif_chunk1_isolation.py.

    Kept in sync deliberately: a different generator would mean a different CRC
    for the same seed, and the whole question here is about CRC recognition.
    """
    rng = random.Random(seed)
    frames = []
    for _ in range(32):
        im = Image.new("RGB", (32, 32), (0, 0, 0))
        px = im.load()
        for _ in range(300):
            px[rng.randrange(32), rng.randrange(32)] = (
                rng.randrange(256),
                rng.randrange(256),
                rng.randrange(256),
            )
        frames.append(im)
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=150, loop=0)
    return buf.getvalue()


class StatusLog:
    """Records every (0x01, 0x00) StatusAck. Never cleared -- see ACK DISCIPLINE."""

    def __init__(self) -> None:
        self.entries: list[tuple[float, int]] = []

    def listen(self, ack) -> None:  # noqa: ANN001 -- driver's ack union
        if getattr(ack, "command_type", None) == 1 and getattr(ack, "command_subtype", None) == 0:
            status = getattr(ack, "status", None)
            if status is not None:
                self.entries.append((time.monotonic(), status))

    def since(self, mark: float) -> list[int]:
        return [status for at, status in self.entries if at > mark]


async def one_upload(client: IDotMatrixClient, log: StatusLog, label: str, data: bytes) -> dict:
    """Uploads data and reports the statuses that arrived for THIS upload."""
    mark = time.monotonic()
    started = time.monotonic()
    error: str | None = None
    try:
        await client.gif.upload_bytes(data)
    except Exception as exc:  # noqa: BLE001 -- recording it IS the measurement
        error = repr(exc)
    elapsed = time.monotonic() - started
    await asyncio.sleep(SETTLE_SECONDS)

    statuses = log.since(mark)
    terminal = statuses[-1] if statuses else None
    print(f"  {label}: {len(statuses)} status ack(s) in {elapsed:.2f}s, "
          f"sequence={statuses}, TERMINAL={terminal}", flush=True)
    if error:
        print(f"    upload raised: {error}", flush=True)
    return {"label": label, "statuses": statuses, "terminal": terminal, "error": error}


def print_table(sequence: str, rows: list[dict]) -> None:
    print("\n=== P2b SUMMARY ============================================================", flush=True)
    print(f"  sequence: {sequence}", flush=True)
    print(f"  {'upload':22s} {'acks':>5s}  {'terminal':>8s}", flush=True)
    for row in rows:
        term = "none" if row["terminal"] is None else str(row["terminal"])
        print(f"  {row['label']:22s} {len(row['statuses']):5d}  {term:>8s}", flush=True)

    terminals = [row["terminal"] for row in rows]
    print("", flush=True)
    if sequence == "fresh":
        distinct = sorted({t for t in terminals if t is not None})
        print(f"  terminal statuses seen across {len(rows)} COLD uploads: {terminals}", flush=True)
        if distinct == [0]:
            print("  => consistent with 'terminal 0 = stored fresh'.", flush=True)
        elif distinct == [3]:
            print("  => ALL COLD UPLOADS ENDED 3. '0 = fresh / 3 = duplicate' is WRONG:", flush=True)
            print("     3 is not duplicate-specific.", flush=True)
        elif len(distinct) > 1:
            print("  => MIXED terminals on identical cold conditions. The mapping is not a", flush=True)
            print("     function of fresh-vs-duplicate at all; something else varies.", flush=True)
    else:
        print(f"  first (cold) terminal: {terminals[0] if terminals else 'none'}", flush=True)
        print(f"  second (same bytes)  : {terminals[1] if len(terminals) > 1 else 'none'}", flush=True)
        if len(terminals) > 1 and terminals[0] == 0 and terminals[1] == 3:
            print("  => matches the tidy mapping: 0 = fresh store, 3 = recognized duplicate.", flush=True)
        elif len(terminals) > 1 and terminals[0] == terminals[1]:
            print("  => SAME terminal for cold and duplicate. The terminal status does NOT", flush=True)
            print("     distinguish a fresh store from a recognized duplicate.", flush=True)
    print("  One run is one data point; repeat before writing a mapping into", flush=True)
    print("  capabilities.py. This probe exists because a single anecdote misled once.", flush=True)
    print("============================================================================", flush=True)


async def main(sequence: str) -> None:
    print(f"sequence: {sequence} -- {SEQUENCES[sequence]}", flush=True)
    print("", flush=True)
    print("NOTHING TO WATCH. The panel plays noise animations while uploading; none of", flush=True)
    print("them is a measurement. Every result is a status code captured in code. The", flush=True)
    print("only thing worth a glance is at the very end: the panel should still be", flush=True)
    print("PLAYING something, not sitting on a clock face.", flush=True)
    print("", flush=True)

    log = StatusLog()
    rows: list[dict] = []
    print("building fixtures ...", flush=True)
    if sequence == "fresh":
        payloads = [(f"cold seed-{seed}", make_big_gif(seed)) for seed in FRESH_SEEDS]
    else:
        data = make_big_gif(DUPLICATE_SEED)
        payloads = [(f"cold seed-{DUPLICATE_SEED}", data), (f"SAME seed-{DUPLICATE_SEED}", data)]
    print(f"  {len(payloads)} payload(s), {len(payloads[0][1])} bytes each", flush=True)

    print("connecting ...", flush=True)
    try:
        async with IDotMatrixClient.connect_to(ADDRESS, SCREEN) as client:
            client.add_response_listener(log.listen)
            for label, data in payloads:
                rows.append(await one_upload(client, log, label, data))
    finally:
        if rows:
            print_table(sequence, rows)


asyncio.run(main(select_sequence(sys.argv[1:])))
