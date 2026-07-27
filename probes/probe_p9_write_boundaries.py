"""P9 -- BLE write-boundary and write-mode matrix (docs/PROBE_PLAN.md, P9).

WHY THIS PROBE EXISTS
---------------------
The transport deliberately RE-SPLITS protocol packets. Every builder splits a
4096-byte outer chunk into 509-byte "BLE packets" (protocol/bytes_.py's
MTU_SIZE_IF_ENABLED), and then BleTransport.write_packets splits those AGAIN,
into whatever this link's write size turns out to be -- see the innermost
`for start in range(0, len(packet), write_size)` loop in transport/ble.py. The
justification written into that method's docstring is a CLAIM, not a measured
fact: "the device reassembles by the length header in each chunk, so BLE write
boundaries don't matter to it."

If that claim is wrong, every low-MTU panel (the BlueZ under-reporters the
write_size_override escape hatch exists for) is silently corrupting frames, and
we would never know, because the device acks receipt regardless. So: send the
same known-good payload at several forced write sizes and compare what actually
appears on the panel.

THE OVERRIDE: NAME AND MECHANISM (confirmed against transport/ble.py)
--------------------------------------------------------------------
The brief's name is right -- `write_size_override` -- but three details matter
and none of them are obvious from the name:

  1. It is a CONSTRUCTOR kwarg on BleTransport, not on IDotMatrixClient. To use
     it the supported way you must build the transport yourself and hand it to
     the client (`IDotMatrixClient(size, transport=BleTransport(mac,
     write_size_override=N))`). That would force a RECONNECT per write size --
     four connects, four chances for a WinRT reconnect to eat the run.
     `_resolve_write_size` re-reads `self._write_size_override` on EVERY write
     and short-circuits before the cached negotiated size, so assigning the
     attribute mid-connection takes effect on the very next write. This probe
     does that (see force_write_size) and stays on one connection all run.

  2. The constructor VALIDATES the override into [20, 517]
     (_MIN_WRITE_SIZE_OVERRIDE .. _MAX_WRITE_SIZE_OVERRIDE). So the constructor
     path CANNOT EXPRESS 18 -- and 18 is not an arbitrary number, it is
     protocol/bytes_.py's own MTU_SIZE_IF_DISABLED, the packet size the vendor
     app uses when MTU negotiation is off. The floor is justified as "ATT_MTU 23
     minus a 3-byte header", which is a statement about the smallest LINK, not
     the smallest WRITE: writing 18 bytes over a link that can carry 20 is
     always legal. Assigning the attribute bypasses that validation, which is
     the only way to cover the brief's 18. Deliberate, and safe in this
     direction only (smaller than negotiated).

  3. THE OVERRIDE ONLY APPLIES TO NO-RESPONSE WRITES. `_resolve_write_size`
     returns _MAX_WRITE_WITH_RESPONSE (512) unconditionally when response=True,
     before it ever looks at the override. Trace it through:

       - write_packets() always calls _resolve_write_size(response=False), so
         its inner splitting DOES honour the override. Its `response` argument
         only decides whether the single FINAL packet is GATT-acked.
       - write(data, response=True) -- the path every flat config command takes
         via _Feature._send -- resolves to 512 and IGNORES the override.

     Consequence, and it is a feature here: clock, scoreboard and reset are
     unaffected by anything this probe does, so the on-panel phase labels stay
     trustworthy at every write size. And the three payloads the brief asks for
     -- DIY frame (display.show_frame), GIF (gif.upload_bytes), 32x32 text
     (text.show) -- are exactly the three that go through write_packets, so all
     three DO honour it. Nothing was skipped for lack of a hook.

TEST CONTENT -- WHAT CORRECT OUTPUT LOOKS LIKE
----------------------------------------------
A frame that looks the same when mangled teaches nothing, so every fixture is
chiral and colour-keyed. The operator should report DEVIATION from these, not
free-form impressions.

  DIY FRAME ("the landmark frame"). Black background, and:
    - four 4x4 corner blocks, all different: TOP-LEFT RED, TOP-RIGHT GREEN,
      BOTTOM-LEFT BLUE, BOTTOM-RIGHT WHITE.
    - a 2px-wide MAGENTA vertical bar at columns 6-7, LEFT of centre.
    - a 2px-tall CYAN horizontal bar at rows 20-21, BELOW centre; cyan wins
      where the two bars cross.
  Reading it: the four distinct corners catch any rotation or mirror; red vs
  blue catches an RGB/BGR swap; the off-centre cross catches a row/column
  transpose or a shifted start offset (a symmetric cross would not). The WHITE
  bottom-right corner is the LAST pixel of the payload, so a dropped trailing
  packet shows up as a dark bottom-right corner while everything else looks
  fine -- the single most likely re-splitting bug, made visible.

  GIF (one per write size, colour-keyed -- see the note below). A dim tinted
  field with a 6x6 WHITE block HOPPING clockwise TL -> TR -> BR -> BL, four
  frames, ~4 fps. Correct = smooth clockwise hop on the right tint. A frozen
  block, a block that only visits some corners, or a wrong tint = wrong.
  Tints, in write-size order: RED, GREEN, BLUE, YELLOW.

  TEXT. The string is the write size itself -- "W18", "W20", "W128", ... --
  scrolling as a marquee. Correct = those exact characters, legible, in order.
  This phase labels itself; garbled or missing characters are the deviation.

WHY THE GIF FIXTURE CHANGES PER WRITE SIZE (and the frame/text do not)
---------------------------------------------------------------------
The device keeps a single-slot CRC of the currently stored gif. Re-sending
byte-identical gif bytes is recognized from chunk 1 and answered SAVED in ~1s
WITHOUT the rest of the transfer ever going on the wire (P2d, 2026-07-25). A
"same payload at every write size" gif would therefore exercise the splitting
exactly once and then measure nothing three times over. So each write size gets
its own tint, making every gif phase a genuine cold transfer. What is compared
across sizes is "did the transfer complete and render correctly", not byte
identity. The DIY frame and the text string have no such dedup and are held
byte-identical across sizes (the text differs only in the label it prints,
which is the point).

Each gif is small enough to be a SINGLE outer chunk, so it goes straight to
SAVED with no NEXT_CHUNK round trip and cannot trip the chunk-2 race. Uploads
use client.gif.upload_bytes -- the SAFE status-aware paced sender. No raw
sender is used anywhere in this probe.

METHOD
------
Reset (04 00 03 80, VERIFIED non-destructive), clock baseline, then read the
link's ACTUAL negotiated no-response write size straight off the characteristic
(transport._resolve_write_size, which is what every real write consults). That
measured number -- not a requested one -- is the "largest" phase and is printed
verbatim, per the brief.

The size list is then built as [18, 20, 128, negotiated], DROPPING any
candidate larger than negotiated. That drop is a safety rule, not a
convenience: forcing a write larger than the link can carry makes bleak raise
inside _write_raw, which triggers the transport's self-healing forced
reconnect-and-retry -- minutes of churn and a polluted run, for a result we
already have (the negotiated number itself). On a link that reports 20, the
matrix legitimately collapses to [18, 20]; record that as the result. Pass
--overrequest to deliberately add a 509-byte phase ABOVE the negotiated size
anyway; off by default, and expected to fail loudly if the link is small.

DIY MODE, AND A TRAP THIS PROBE STEPS AROUND
--------------------------------------------
BleDisplay caches "DIY mode is active" per connection and only sends the entry
command when that cache is False. Every other phase here (scoreboard, clock,
gif, text) takes the panel OUT of DIY behind the display's back, and full
frames sent into a non-DIY panel are SILENTLY SWALLOWED while still acking
accepted=True (2026-07-20). Un-handled, that would read as "write size 20 broke
the frame". So invalidate_diy_mode() is called before EVERY show_frame.

ACK INSTRUMENTATION -- THE BUG THIS PROBE REFUSES TO REPEAT
------------------------------------------------------------
On 2026-07-26 a probe printed its ack report IMMEDIATELY after sending and then
cleared the list at the phase boundary. The device's reply had not arrived yet
(~0.3s, and up to ~4.3s for effects), so the report read empty every time, and
"all four 0x0d frames drew no ack whatsoever" was published as a device
behaviour when it was an instrumentation bug. An entire hardware run was spent
on it. Therefore, here: report_acks is ASYNC, sleeps ACK_SETTLE_SECONDS BEFORE
reading, prints the send->ack delta for every entry, and clears the list only
AFTER printing it.

READOUT
-------
  * Every write size renders the landmark frame, the hopping gif and the text
    IDENTICALLY => the re-splitting is correct, write boundaries are invisible
    to the device, and write_packets' docstring claim is now measured. This is
    the expected result and the one that validates the BlueZ low-MTU escape
    hatch for every panel we cannot test.
  * A frame renders correctly at 509 but is corrupted, partial or absent at 18
    or 20 => re-splitting is BROKEN for small writes, the low-MTU escape hatch
    is unsafe, and every under-reporting panel is being fed garbage. Record
    which payload types fail: frame-only implicates the 9-byte DIY header,
    all-three implicates the transport loop itself.
  * The BOTTOM-RIGHT corner goes dark (or the text loses its last character)
    only at small sizes => the final packet of the final chunk is being
    dropped, i.e. an off-by-one in the re-splitting tail, not a device-side
    reassembly failure.
  * Wall time grows roughly as (payload / write size) with no other change =>
    small writes cost throughput and nothing else. A NON-linear blowup (or GATT
    errors) at a small size is a rate problem, not a boundary problem, and
    belongs to P4, not here.
  * The write-MODE pair (last packet GATT-acked vs not) renders identically =>
    wait_for_device is a flow-control choice with no rendering consequence.
    Note the honest limit of this comparison: this transport NEVER sends a
    frame as all-response writes; `response=True` acks only the single final
    packet. "Write-with-response" throughout is not a mode this driver has.
  * ANY GATT error at a size <= negotiated is a finding in itself -- record the
    exception text verbatim.

USAGE
-----
    python probes/probe_p9_write_boundaries.py
    python probes/probe_p9_write_boundaries.py C:/Windows/Fonts/consola.ttf
    python probes/probe_p9_write_boundaries.py --overrequest
    python probes/probe_p9_write_boundaries.py 514              # re-observe one size
    python probes/probe_p9_write_boundaries.py 128 514
    python probes/probe_p9_write_boundaries.py C:/Windows/Fonts/consola.ttf 514 --overrequest

Arguments are order-free and identified by shape: `--overrequest` is the flag,
a DECIMAL integer is a write size, anything else must be an existing font path.
Anything else at all prints the accepted values and exits non-zero, before any
BLE contact.

Giving one or more sizes runs ONLY those, in the order given, and then the
write-mode pair as usual. This exists because re-observing one block should not
cost the whole matrix: the first hardware run (below) settled 18/20/128 and the
operator only needed the 514 block and the mode pair again.

A requested size at or above the link's negotiated write size is CLAMPED to the
negotiated value and the value actually used is printed -- not skipped. The
negotiated size is only discoverable after connecting, so "514" carried over
from a previous run's log keeps meaning "the big one" even on a link that
negotiates something else. Sizes are otherwise unvalidated at parse time for
the same reason; only values that cannot be a write size at all (zero,
negative, non-decimal) are refused up front.

Gif tints are keyed to the size's place in the DEFAULT matrix, not to its
position in the run, so a 514-only re-run shows the same tint 514 showed in the
full run and the operator's notes keep lining up.

The write-mode pair ALWAYS runs, at the negotiated size, whatever was selected.
It is a MODE test, not a size test. It labels itself on the panel as 999 | 1
and 999 | 2 rather than reusing the negotiated size as count1 -- on 2026-07-27
the operator saw "514" label both the 514 size phase and the mode pair and read
the second as a repeat of the first.

No font ships with this package. A TTF path may be given as an argument;
otherwise a few standard system fonts are tried and, if none exist, the text
phases are SKIPPED loudly rather than failing the run.

Estimated runtime: ~7 minutes for the full four-size matrix (~45 s per size,
plus ~40 s of baseline and write-mode work). A single-size re-run is ~1.5
minutes: ~40 s for the size block, ~25 s for the write-mode pair, ~10 s of
connect and baseline. Under the ~15 minute budget either way.

SAFETY
------
No graffiti commands at all, so the 255-pixel-per-command guardrail (a
256-pixel command crashed the panel's BLE stack on 2026-07-25) is not
approached from any direction. No set_password/verify_password, no ae00/ae01
writes, no experimental namespace, no delete_device_data. common.reset()
(04 00 03 80) is the only state-clearing command used and is verified-safe.
Write sizes above the negotiated maximum are refused unless --overrequest is
passed explicitly.

RESULT (2026-07-27, CLOSED after a run-1 re-observation of the 514 block and
write-mode pair): RE-SPLITTING IS CORRECT AT EVERY SIZE TESTED.

  1. Write sizes 18, 20, 128 AND 514 (the link's negotiated size) ALL RENDERED
     CORRECTLY. The landmark frame came up with all four corners right (TL
     red, TR green, BL blue, BR white), both off-centre bars present, and NO
     dark bottom-right corner at any size -- so the final packet of the final
     chunk is not being dropped, at any of the four. The gif and the text
     were correct at all four sizes too.
  2. Therefore: the transport's packet re-splitting is proven correct down to
     18 bytes per write, across all three payload types and the full size
     range from 18 to the link's negotiated 514, and write boundaries are
     invisible to the device. write_packets' docstring claim ("the device
     reassembles by the length header in each chunk, so BLE write boundaries
     don't matter to it") is now MEASURED rather than assumed, and the BlueZ
     low-MTU escape hatch is SAFE to recommend for panels we cannot test.
  3. The link negotiated 514 bytes -- above the 509 the protocol builders split
     at, so on this host the transport re-splits nothing in the default
     configuration, and --overrequest is a no-op (509 is not above 514).
  4. Send-side wall times for the DIY frame (3081 payload bytes): 1.22 s @18,
     1.05 s @20, 0.87 s @128, 0.67 s @514. Sub-linear in write size, so the
     per-write overhead is not the dominant cost at these sizes -- small writes
     are ~1.8x slower, not ~28x.
  5. WRITE MODE, identical payload at 514, re-observed and CONFIRMED: same
     three corners, correct bar orientation and corner colour for both
     wait_for_device values. Unacked writes (response=False) ran 3-6x faster
     than response-acked writes across the sizes measured here and in
     probe_p9's earlier pass (0.67 s with response=True vs 0.11 s with
     response=False at 514), with no rendering difference either way. Worth
     carrying into P4's rate work and into any streaming guidance:
     wait_for_device is not free.

No further P9 probes planned. See capabilities.py's display.write_without_
response entry for the recorded evidence.
"""

import asyncio
import io
import os
import sys
import time

from PIL import Image, ImageDraw

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol.bytes_ import MTU_SIZE_IF_DISABLED, MTU_SIZE_IF_ENABLED
from pyidotmatrix.transport.ble import _MAX_WRITE_SIZE_OVERRIDE, _MIN_WRITE_SIZE_OVERRIDE

ADDRESS = "6D:FD:F8:A0:3E:AF"

# How long to wait after a send before READING the ack list. Non-negotiable:
# see the ack-instrumentation section of the module docstring. Device replies
# have been measured at ~0.3s (gif/frame) and ~4.3s (effect); 2.0s covers the
# families this probe uses with margin, and a phase that reports zero acks
# after this wait has genuinely received none.
ACK_SETTLE_SECONDS = 2.0

# Candidate forced write sizes, smallest first. 18 is protocol/bytes_.py's
# MTU_SIZE_IF_DISABLED (the vendor app's own no-MTU packet size) and is BELOW
# the transport constructor's validation floor -- see the module docstring. 20
# is that floor, i.e. ATT_MTU 23 minus the 3-byte ATT header. 128 is the
# brief's medium band (100-185). The link's real negotiated size is appended at
# runtime; anything larger than it is dropped.
CANDIDATE_WRITE_SIZES = (MTU_SIZE_IF_DISABLED, _MIN_WRITE_SIZE_OVERRIDE, 128)

# One distinct tint per write size, in order -- the gif fixture must differ per
# size or single-slot CRC recognition short-circuits the transfer entirely.
GIF_TINTS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255))
GIF_TINT_NAMES = ("RED", "GREEN", "BLUE", "YELLOW", "MAGENTA")

FRAME_WATCH_SECONDS = 6
GIF_WATCH_SECONDS = 8
TEXT_WATCH_SECONDS = 12
LABEL_SECONDS = 4

# count1 for the write-MODE pair's on-panel label. Deliberately NOT the
# negotiated write size: on 2026-07-27 the operator saw "514" label both the 514
# size phase and the mode pair and read the second as a repeat of the first.
# 999 cannot collide with any plausible write size, and it is scoreboard's own
# MAX_SCORE so it is never silently clamped into a different number.
MODE_LABEL_SENTINEL = 999

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

CANVAS = 32


def usage_and_exit(problem: str) -> None:
    """Prints the accepted values and exits non-zero. Every rejection path comes
    through here, so a typo can never half-run the matrix."""
    print(f"{problem}", flush=True)
    print("usage: probe_p9_write_boundaries.py [FONT.ttf] [WRITE_SIZE ...] [--overrequest]", flush=True)
    print("  WRITE_SIZE     one or more positive DECIMAL integers, e.g. 18 20 128 514.", flush=True)
    print(
        f"                 Omitted, the full default matrix runs:"
        f" {list(CANDIDATE_WRITE_SIZES)} plus the link's negotiated size.",
        flush=True,
    )
    print("                 Given, ONLY those sizes run, in the order given.", flush=True)
    print("                 A size at or above the negotiated size is CLAMPED to it and", flush=True)
    print("                 the value actually used is printed (the negotiated size is", flush=True)
    print("                 only discoverable after connecting, so it cannot be", flush=True)
    print("                 validated up front).", flush=True)
    print("  FONT.ttf       an existing TTF/OTF path; omitted, standard system fonts are tried.", flush=True)
    print("  --overrequest  add a deliberate over-sized phase; composable with a size list.", flush=True)
    print("The write-mode pair ALWAYS runs afterwards, at the negotiated size, whatever", flush=True)
    print("is selected -- it is a MODE test, not a size test.", flush=True)
    raise SystemExit(2)


def parse_args(argv: list[str]) -> tuple[str | None, tuple[int, ...], bool]:
    """Returns (font_path, requested_sizes, overrequest).

    Parsed entirely before any BLE contact. Arguments are order-free and
    identified by shape: `--overrequest` is the flag, a decimal integer is a
    write size, anything else must be an existing font path. Sizes keep the
    order the operator gave them; an empty tuple means "the default matrix",
    which is byte-for-byte the pre-selector behaviour.

    Sizes are NOT range-checked here on purpose. The only meaningful ceiling is
    the link's negotiated write size, which is unknowable until we have
    connected -- so an out-of-range size is clamped and reported at that point
    (see main) rather than rejected now. Only values that cannot be a write size
    at all (zero, negative, non-decimal) are refused here.
    """
    overrequest = False
    font_path: str | None = None
    sizes: list[int] = []

    for argument in argv:
        if argument == "--overrequest":
            overrequest = True
        elif argument.startswith("--"):
            usage_and_exit(f"unknown option {argument!r}")
        elif argument.isdigit():          # decimal only, per the brief
            value = int(argument)
            if value < 1:
                usage_and_exit(f"write size {argument!r} must be a positive integer")
            sizes.append(value)
        elif os.path.exists(argument):
            if font_path is not None:
                usage_and_exit(f"more than one font path given ({font_path!r} and {argument!r})")
            font_path = argument
        else:
            usage_and_exit(f"unrecognized argument {argument!r} -- not a decimal write size, not an existing file")

    if font_path is None:
        for candidate in FONT_CANDIDATES:
            if os.path.exists(candidate):
                font_path = candidate
                break
    return font_path, tuple(sizes), overrequest


def build_landmark_frame(bar_row: int = 20, corner_br: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    """The asymmetric DIY test frame described in the module docstring.

    Row-major RGB, top-left origin (the geometry contract proven by P8,
    probes/probe_p8_geometry.py). bar_row and corner_br exist only so the
    write-MODE comparison can put two TELLABLE-APART frames on screen back to
    back; every write-size phase uses the defaults.
    """
    buffer = bytearray(CANVAS * CANVAS * 3)

    def put(x: int, y: int, rgb: tuple[int, int, int]) -> None:
        offset = (y * CANVAS + x) * 3
        buffer[offset:offset + 3] = bytes(rgb)

    def block(x0: int, y0: int, size: int, rgb: tuple[int, int, int]) -> None:
        for y in range(y0, y0 + size):
            for x in range(x0, x0 + size):
                put(x, y, rgb)

    block(0, 0, 4, (255, 0, 0))               # top-left RED
    block(CANVAS - 4, 0, 4, (0, 255, 0))      # top-right GREEN
    block(0, CANVAS - 4, 4, (0, 0, 255))      # bottom-left BLUE
    block(CANVAS - 4, CANVAS - 4, 4, corner_br)  # bottom-right -- LAST pixels of the payload

    for y in range(6, 26):                    # magenta vertical bar, LEFT of centre
        put(6, y, (255, 0, 255))
        put(7, y, (255, 0, 255))
    for x in range(6, 26):                    # cyan horizontal bar, drawn over the magenta
        put(x, bar_row, (0, 255, 255))
        put(x, bar_row + 1, (0, 255, 255))

    return bytes(buffer)


def build_hop_gif(tint: tuple[int, int, int]) -> bytes:
    """Four frames: a 6x6 white block hopping clockwise through the corners of
    a dim tinted field. Small enough to be ONE outer chunk, so the upload goes
    straight to SAVED with no NEXT_CHUNK round trip and no chunk-2 race."""
    background = tuple(channel // 3 for channel in tint)
    frames = []
    for x, y in ((2, 2), (24, 2), (24, 24), (2, 24)):  # TL -> TR -> BR -> BL
        image = Image.new("RGB", (CANVAS, CANVAS), background)
        ImageDraw.Draw(image).rectangle([x, y, x + 5, y + 5], fill=(255, 255, 255))
        frames.append(image)
    buffer = io.BytesIO()
    frames[0].save(
        buffer, format="GIF", save_all=True, append_images=frames[1:], duration=250, loop=0
    )
    return buffer.getvalue()


def force_write_size(client: IDotMatrixClient, size: int | None) -> None:
    """Forces the transport's no-response write size for subsequent writes.

    Assigns BleTransport._write_size_override directly rather than constructing
    a transport per size. Two reasons, both in the module docstring: it avoids
    one reconnect per write size, and it is the ONLY way to reach 18, which the
    constructor's [20, 517] validation refuses even though 18 is the vendor
    app's own MTU_SIZE_IF_DISABLED packet size. Since that bypasses the
    constructor's guard, the guard is re-stated here -- a negative or zero
    override empties the chunking loop's range() and drops every write with no
    error at all, which is exactly the failure the validation exists to
    prevent. None restores the link's reported size.
    """
    if size is not None and not (0 < size <= _MAX_WRITE_SIZE_OVERRIDE):
        raise ValueError(f"refusing an implausible write size {size!r}")
    client._transport._write_size_override = size


async def main(font_path: str | None, requested_sizes: tuple[int, ...], overrequest: bool) -> None:
    # Printed before any BLE contact so the operator knows what they are about to
    # watch. The resolved list (after clamping against the negotiated size) is
    # printed again once we are connected.
    if requested_sizes:
        print(f"write sizes REQUESTED: {list(requested_sizes)} (clamped to the negotiated size once connected)",
              flush=True)
    else:
        print(
            f"write sizes REQUESTED: none given -> full default matrix"
            f" {list(CANDIDATE_WRITE_SIZES)} plus the negotiated size",
            flush=True,
        )
    print(f"--overrequest: {'ON' if overrequest else 'off'}", flush=True)
    print("the write-mode pair runs after the sizes, always at the negotiated size", flush=True)
    print(f"font: {font_path or 'NONE FOUND -- text phases will be SKIPPED'}", flush=True)
    print("connecting ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        acks: list[tuple[float, object]] = []
        unsubscribe = client.add_response_listener(lambda ack: acks.append((time.perf_counter(), ack)))

        async def report_acks(label: str, sent_at: float) -> None:
            """Waits for the device to actually reply, THEN reports and clears.

            The sleep is the whole point -- reading the list synchronously
            after a send is the 2026-07-26 instrumentation bug that invented a
            device behaviour out of nothing (module docstring). Every entry is
            printed with its send->ack delta so a slow reply can never again be
            mistaken for silence, and the list is cleared only after printing.
            """
            await asyncio.sleep(ACK_SETTLE_SECONDS)
            if acks:
                print(f"  {label}: {len(acks)} ack(s) after {ACK_SETTLE_SECONDS}s:", flush=True)
                for at, ack in acks:
                    print(f"    send+{at - sent_at:6.2f}s  {ack!r}", flush=True)
            else:
                print(
                    f"  {label}: *** ZERO ACKS within {ACK_SETTLE_SECONDS}s of the send *** "
                    f"-- record this, it is a result",
                    flush=True,
                )
            acks.clear()

        results: list[tuple[str, str, str, str]] = []  # size, payload, wall time, note

        # --- baseline ---------------------------------------------------------
        try:
            print("resetting device to a known state ...", flush=True)
            await client.common.reset()
            await asyncio.sleep(4)
            await client.clock.show()
            await asyncio.sleep(3)
            acks.clear()
            print("baseline: clock. acks cleared.", flush=True)
        except Exception as ex:
            print(f"  reset/clock baseline FAILED: {ex!r}", flush=True)

        # The link's REAL no-response write size, read from the same code path
        # every write consults. This is the measured number the brief asks for
        # -- not a requested one. On WinRT it is frequently well below the
        # 509/512 the brief suggests trying.
        negotiated = await client._transport._resolve_write_size(response=False)
        print(f"\nNEGOTIATED no-response write size: {negotiated} bytes", flush=True)
        print(f"  (protocol builders split at {MTU_SIZE_IF_ENABLED}; transport re-splits to the above)", flush=True)
        print(
            f"  (constructor validation would allow only"
            f" {_MIN_WRITE_SIZE_OVERRIDE}..{_MAX_WRITE_SIZE_OVERRIDE})",
            flush=True,
        )

        # The default matrix. Always computed, even when the operator selected a
        # subset, because it also fixes the CANONICAL ORDER that gif tints are
        # keyed to -- see tint_index_by_size below.
        canonical: list[int] = []
        for candidate in (*CANDIDATE_WRITE_SIZES, negotiated):
            if candidate <= negotiated and candidate not in canonical:
                canonical.append(candidate)
        skipped = [c for c in CANDIDATE_WRITE_SIZES if c > negotiated]
        if skipped:
            print(f"  DROPPED from the default matrix (larger than the link can carry): {skipped}", flush=True)

        sizes: list[int] = []
        if requested_sizes:
            # Explicit selection. A requested size at or above the negotiated
            # size is CLAMPED rather than skipped -- the negotiated value is
            # only discoverable here, after connecting, so "514" typed from a
            # previous run's log has to keep meaning "the big one" even if this
            # link negotiates something different.
            for wanted in requested_sizes:
                used = min(wanted, negotiated)
                if used != wanted:
                    print(f"  requested {wanted} -> CLAMPED to the negotiated {negotiated}", flush=True)
                if used in sizes:
                    print(f"  requested {wanted} -> {used}, already selected; not repeating it", flush=True)
                    continue
                sizes.append(used)
        else:
            sizes = list(canonical)

        if overrequest:
            if negotiated < MTU_SIZE_IF_ENABLED:
                sizes.append(MTU_SIZE_IF_ENABLED)
                print(
                    f"  --overrequest: adding a deliberate {MTU_SIZE_IF_ENABLED}-byte OVER-REQUEST phase",
                    flush=True,
                )
            else:
                print(
                    f"  --overrequest: NO-OP on this link -- {MTU_SIZE_IF_ENABLED} is not above"
                    f" the negotiated {negotiated}, so there is nothing to over-request",
                    flush=True,
                )

        if not sizes:
            print("  no write sizes to run; nothing to do.", flush=True)

        # Gif tints are keyed to the size's place in the CANONICAL matrix, not to
        # its position in this run. A 514-only re-run must show the same tint 514
        # showed in the full run, or the operator's notes stop lining up. Sizes
        # outside the canonical matrix (an over-request, or an unusual hand-picked
        # value) continue the sequence after it.
        tint_index_by_size = {size: index for index, size in enumerate(canonical)}
        for size in sizes:
            if size not in tint_index_by_size:
                tint_index_by_size[size] = len(tint_index_by_size)

        tint_summary = ", ".join(
            f"{size}={GIF_TINT_NAMES[tint_index_by_size[size] % len(GIF_TINT_NAMES)]}" for size in sizes
        )
        print(f"  write sizes this run: {sizes}", flush=True)
        print(f"  gif tints: {tint_summary}", flush=True)

        # --- the matrix -------------------------------------------------------
        for size in sizes:
            over = size > negotiated
            index = tint_index_by_size[size]
            tint = GIF_TINTS[index % len(GIF_TINTS)]
            tint_name = GIF_TINT_NAMES[index % len(GIF_TINT_NAMES)]
            banner = f"WRITE SIZE {size}" + (" (OVER-REQUEST -- expected to fail)" if over else "")
            print(f"\n=================== {banner} ===================", flush=True)

            try:
                # Flat command: goes through write(response=True), which resolves
                # to 512 and IGNORES the override -- so this label is legible at
                # every write size, including a broken one.
                await client.scoreboard.show(size, 0)
                await asyncio.sleep(LABEL_SECONDS)
            except Exception as ex:
                print(f"  scoreboard label FAILED: {ex!r}", flush=True)

            force_write_size(client, size)

            # --- payload 1: one full DIY frame --------------------------------
            label = f"size {size} / DIY frame"
            try:
                # Mandatory: scoreboard/clock/gif/text all left DIY mode behind
                # the display's back, and a frame into a non-DIY panel is
                # swallowed while still acking accepted=True.
                client.display.invalidate_diy_mode()
                sent_at = time.perf_counter()
                await client.display.show_frame(build_landmark_frame(), wait_for_device=True)
                elapsed = time.perf_counter() - sent_at
                print(f"  frame sent in {elapsed:.2f}s (3081 payload bytes at {size}/write)", flush=True)
                await report_acks(f"{label} (expect 05 00 00 00 01)", sent_at)
                print(
                    f"  WATCH ({FRAME_WATCH_SECONDS}s): corners TL=RED TR=GREEN BL=BLUE BR=WHITE;"
                    f" magenta bar LEFT of centre, cyan bar BELOW centre."
                    f" Report ANY deviation -- especially a DARK BOTTOM-RIGHT corner.",
                    flush=True,
                )
                await asyncio.sleep(FRAME_WATCH_SECONDS)
                results.append((str(size), "DIY frame", f"{elapsed:.2f}s", "sent"))
            except Exception as ex:
                print(f"  {label} FAILED: {ex!r}", flush=True)
                results.append((str(size), "DIY frame", "-", f"FAILED {ex!r}"))

            # --- payload 2: one small GIF upload ------------------------------
            label = f"size {size} / GIF ({tint_name})"
            try:
                gif_bytes = build_hop_gif(tint)
                print(f"  gif fixture: {len(gif_bytes)} bytes, tint {tint_name}", flush=True)
                sent_at = time.perf_counter()
                await client.gif.upload_bytes(gif_bytes)  # SAFE status-aware paced sender
                elapsed = time.perf_counter() - sent_at
                print(f"  gif uploaded in {elapsed:.2f}s", flush=True)
                await report_acks(f"{label} (expect a StatusAck status=3 SAVED)", sent_at)
                print(
                    f"  WATCH ({GIF_WATCH_SECONDS}s): a {tint_name} field with a WHITE block"
                    f" hopping CLOCKWISE TL -> TR -> BR -> BL. Report a frozen block,"
                    f" a skipped corner, or a wrong colour.",
                    flush=True,
                )
                await asyncio.sleep(GIF_WATCH_SECONDS)
                results.append((str(size), f"GIF {tint_name}", f"{elapsed:.2f}s", "sent"))
            except Exception as ex:
                # Includes UploadError: the safe sender has already spent its
                # one whole-upload retry by the time it raises here.
                print(f"  {label} FAILED: {ex!r}", flush=True)
                results.append((str(size), f"GIF {tint_name}", "-", f"FAILED {ex!r}"))

            # --- payload 3: one 32x32 text command ----------------------------
            label = f"size {size} / text"
            if font_path is None:
                print(f"  {label} SKIPPED -- no font available", flush=True)
                results.append((str(size), "text", "-", "SKIPPED (no font)"))
            else:
                try:
                    message = f"W{size}"
                    sent_at = time.perf_counter()
                    await client.text.show(message, font_path=font_path, font_size=16)
                    elapsed = time.perf_counter() - sent_at
                    print(f"  text {message!r} sent in {elapsed:.2f}s", flush=True)
                    await report_acks(f"{label} (expect a StatusAck on (3, 0))", sent_at)
                    print(
                        f"  WATCH ({TEXT_WATCH_SECONDS}s): the marquee must read exactly {message!r}."
                        f" Report missing, garbled or reordered characters.",
                        flush=True,
                    )
                    await asyncio.sleep(TEXT_WATCH_SECONDS)
                    results.append((str(size), "text", f"{elapsed:.2f}s", f"sent {message!r}"))
                except Exception as ex:
                    print(f"  {label} FAILED: {ex!r}", flush=True)
                    results.append((str(size), "text", "-", f"FAILED {ex!r}"))

        # --- write-mode comparison, at the negotiated size --------------------
        # The honest scope of this comparison is in the module docstring: this
        # transport never sends a frame as all-response writes. wait_for_device
        # decides whether the SINGLE FINAL packet of the final chunk is
        # GATT-acked; every other packet is no-response either way. So this is
        # "last packet acked" vs "nothing acked", which is the only write-mode
        # axis the driver actually exposes.
        print("\n=================== WRITE MODE: response vs no-response ===================", flush=True)
        force_write_size(client, None)
        print(f"  restored to the negotiated size ({negotiated})", flush=True)
        for note_line in (
            f"NOTE: this pair ALWAYS runs at the negotiated size ({negotiated}), whatever sizes were",
            "selected. It is a MODE test, not a size test -- the two frames below differ ONLY in",
            f"whether the final packet is GATT-acked. If {negotiated} also ran as a size phase above,",
            "that is the SAME number appearing for a DIFFERENT reason, not a repeat of it. On the",
            f"panel this pair labels itself {MODE_LABEL_SENTINEL} | 1 and {MODE_LABEL_SENTINEL} | 2,"
            f" never {negotiated} | n, so the",
            "two are distinguishable from the panel alone.",
        ):
            print(f"  {note_line}", flush=True)
        for wait_for_device, bar_row, corner, name in (
            (True, 20, (255, 255, 255), "response=True  (final packet GATT-acked), cyan bar LOW, corner WHITE"),
            (False, 10, (255, 128, 0), "response=False (nothing GATT-acked),      cyan bar HIGH, corner ORANGE"),
        ):
            try:
                # Sentinel count1, NOT the negotiated size: on 2026-07-27 the
                # operator saw "514" labelling both the 514 size phase and this
                # mode pair and read the pair as a repeat of the size phase.
                # 999 cannot collide with any write size (and is scoreboard's
                # own MAX_SCORE, so it is never clamped into something else).
                await client.scoreboard.show(MODE_LABEL_SENTINEL, 1 if wait_for_device else 2)
                await asyncio.sleep(LABEL_SECONDS)
                client.display.invalidate_diy_mode()
                sent_at = time.perf_counter()
                await client.display.show_frame(
                    build_landmark_frame(bar_row, corner), wait_for_device=wait_for_device
                )
                elapsed = time.perf_counter() - sent_at
                print(f"  {name}: sent in {elapsed:.2f}s", flush=True)
                await report_acks(f"write mode wait_for_device={wait_for_device}", sent_at)
                print(
                    f"  WATCH ({FRAME_WATCH_SECONDS}s): same three corners (RED/GREEN/BLUE);"
                    f" bottom-right must be {'WHITE' if wait_for_device else 'ORANGE'}"
                    f" and the cyan bar {'BELOW' if bar_row == 20 else 'ABOVE'} centre.",
                    flush=True,
                )
                await asyncio.sleep(FRAME_WATCH_SECONDS)
                results.append(("mode", f"wait_for_device={wait_for_device}", f"{elapsed:.2f}s", "sent"))
            except Exception as ex:
                print(f"  write mode wait_for_device={wait_for_device} FAILED: {ex!r}", flush=True)
                results.append(("mode", f"wait_for_device={wait_for_device}", "-", f"FAILED {ex!r}"))

        # --- summary ----------------------------------------------------------
        print("\n---- send-side summary (the VISUAL result is the operator's to report) ----", flush=True)
        print(f"{'size':>8}  {'payload':<16} {'wall':>8}  note", flush=True)
        for size_text, payload, wall, note in results:
            print(f"{size_text:>8}  {payload:<16} {wall:>8}  {note}", flush=True)

        print("\nverdict to record:", flush=True)
        print("  identical rendering at every size => re-splitting is CORRECT; the low-MTU", flush=True)
        print("                                       escape hatch is safe on untested panels.", flush=True)
        print("  corrupt/absent only at 18-20      => re-splitting is BROKEN for small writes.", flush=True)
        print("  dark BOTTOM-RIGHT corner only     => the FINAL packet of the final chunk is", flush=True)
        print("                                       being dropped (tail off-by-one).", flush=True)
        print("  wall time ~ payload/write size    => small writes cost throughput only.", flush=True)

        force_write_size(client, None)
        unsubscribe()
        await client.clock.show()
        print("clock restored. done.", flush=True)


_font_path, _requested_sizes, _overrequest = parse_args(sys.argv[1:])
asyncio.run(main(_font_path, _requested_sizes, _overrequest))
