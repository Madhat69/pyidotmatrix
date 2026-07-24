# Protocol Notes

This is the SDK's moat: hardware truths that don't live anywhere else, each
one earned by a dated probe against a real panel. If you're building
something non-trivial on top of this driver — sustained animation, a daemon
that outlives a single connection, anything latency-sensitive — read this
page before the API reference.

Primary hardware reference throughout: one 32×32 panel (name prefix `IDM-`).
Where a claim is panel-size-specific, it says so.

## Acks confirm receipt, not effect

The device pushes a status notification for most commands it recognizes —
accept or reject. **That notification says the device understood the bytes,
not that it did what you asked.** Two hardware-confirmed ways this bites:

- **DIY entry mode 3** (flash-free, no-clear) is acked every time, but
  silently fails to take over an active effect/clock state — the device just
  stays in whatever mode it was in. Mode 1 (clear) always takes.
- Several commands are acked and then simply do nothing observable on the
  reference panel: `common.freeze_screen`, `common.set_speed`,
  `effect.speed` values other than the historical default,
  `experimental.set_time_indicator`, `music_sync.send_image_rhythm`. See the
  [Hardware Compatibility table](hardware-compatibility.md) for the specific
  evidence behind each.

Treat every acked-but-unverified feature as "the device didn't complain,"
not "the device did it." This SDK does not hide or compensate for these gaps
— an ack that lies is documented as an ack that lies, feature by feature, in
`pyidotmatrix/capabilities.py`.

A separate, narrower ack shape exists for chunked uploads (Timer, Schedule,
text): a 3-way `StatusAck` (`STATUS_NEXT_CHUNK` / `STATUS_SAVED` /
`STATUS_FAILED`) rather than a boolean accept/reject. A `SAVED` status is a
success, never a rejection — this SDK previously misread it as one and
shipped a "broken" feature (32×32 text) that was, in fact, working; see
`pyidotmatrix/protocol/response.py` for the full account.

## Write-with-response is flow control

A GATT write-with-response isn't just a BLE-level delivery confirmation on
this device — the device withholds the response until it has *finished
processing* the command. That makes write-with-response double as
application-level flow control for free: a full framebuffer upload
(`show_frame`) takes roughly 1.5 s of device-side processing, and awaiting
the response is how the SDK knows the device is ready for the next one.

Two related facts:

- Commands with a known ack key are awaited by default
  (`verify_commands=True`); see
  [Getting Started § Rejections are loud by default](getting-started.md#5-rejections-are-loud-by-default).
- Sending faster than the device drains (e.g. flooding unacked frames) queues
  device-side and drains at roughly 0.67 fps; the device self-recovers rather
  than locking up.

## Chunked uploads

Timer (alarm) content, Schedule theme content, and GIF uploads all go through
the same handshake: split into 4096-byte outer chunks, send one, wait for its
`StatusAck`, repeat.

- `STATUS_NEXT_CHUNK` (1) → send the next chunk.
- `STATUS_SAVED` (3) → done. **A single-chunk upload skips straight to
  `SAVED`** — don't assume you'll always see a `NEXT_CHUNK` first.
- `STATUS_FAILED` (0), or no ack within the timeout → the SDK raises
  `UploadError`.
- **Duplicates happen.** The hardware can emit the same status twice for one
  chunk; the upload loop drains a stale queued ack before sending the next
  chunk so a duplicate never gets mistaken for the next chunk's response.

## Persistence is per mode kind

What survives a disconnect (or the whole connection dying) depends on *which*
mode was active, not on anything the SDK controls:

| Mode kind | Survives clean disconnect | Survives power-cycle |
|---|---|---|
| Effect | ✅ | ✅ (flash-persists — observed surviving 3 days) |
| Fullscreen color | ✅ | ✅ (flash-persists) |
| Clock | ❌ (reverts) | ❌ |
| DIY framebuffer | ❌ (reverts in ~2 s) — **unless** quit mode 2 (keep-frame) was used, in which case the kept frame survives a clean disconnect | ❌ (never) |

*How* a connection ends also matters: a clean disconnect reverts an
unparked DIY frame within about 2 seconds; an abrupt link loss (radio drop,
crash) freezes the last frame on screen indefinitely instead.

## Endianness

Every multi-byte header field in the Timer and Schedule chunked-upload
headers is **little-endian on the wire**. This was the opposite of the first
reading of the decompiled source (`short2Bytes` looks big-endian in
isolation, but the call sites swap the bytes before use) — a good example of
why every claim in this SDK's docs cites a probe or a full call-site trace,
not just a function signature read in isolation.

## Known firmware rejections on 32×32

- The **generic/legacy text packet** (`build_text_packet`, used when no
  `screen_size` is passed) renders **truncated** on 32×32 — `"HELLO"` came
  out `"HEL"`. Use `screen_size=ScreenSize.SIZE_32x32` on `TextFeature` (the
  client does this automatically) to get the per-size builder that renders
  fully.
- The **screen-timeout family** (`set_screen_timeout` / `read_screen_timeout`)
  produces no ack and no visible effect at all on the reference panel —
  likely a model-specific feature this panel simply doesn't implement.
- **Graffiti header byte 3** only accepts the value `1` (what the vendor app
  hardcodes); `2` is explicitly nacked, and `0`/`3`/`4` are acked but
  silently swallowed — nothing draws.

## Windows / WinRT resilience

After a host suspend/resume, bleak's WinRT backend can report a client as
connected with GATT services resolved while the underlying session is
actually dead — not a crash, not a visible disconnect event, just silent
write failures forever afterward. The transport detects this on the first
failed write and forces a clean reconnect (rebuild the `BleakClient`, retry
the write once) rather than requiring the caller to notice and recover
manually. This is undocumented in bleak itself; if you're debugging "writes
just stopped working after my laptop woke up" on Windows, this is why it
doesn't happen here.

## Streaming & performance

Benchmarked directly against a real 32×32 panel (`probes/probe_streaming_benchmark.py`),
motivated by two independent community projects pushing this protocol harder
than the vendor app does: [IDotMatrixXLedFx](https://github.com/suchyindustries/IDotMatrixXLedFx)
(24–28 fps unacked DIY streaming) and [idotmatrix-overclocked](https://github.com/pracucci/idotmatrix-overclocked)
(playable 64×64 games).

**The headline number: the panel renders full DIY frames at a hard ~1.75 fps
cap, regardless of send rate or write mode.** Findings:

- **Acked full frames**: 1.25–1.35 fps. Dropping the ack *wait* alone (still
  writing with response) changes essentially nothing (1.30 fps) — the
  round-trip itself is the bottleneck, not the waiting.
- **Write-without-response** is honored by the reference panel: the BLE
  radio ingests up to ~167 fps of unacked writes, but the panel still only
  *renders* at the same ~1.75 fps ceiling — it samples the latest frame in
  its queue and drops the rest. Its fa03 notifications under this mode track
  frames **processed**, not frames received, so don't use notification
  cadence as a receive-rate proxy while streaming unacked.
- This is a firmware property, not universal across the ecosystem: LumiSync's
  independent reverse-engineering notes report write-without-response being
  *ignored* on their unit. Treat write-without-response support as
  per-firmware-variant, not a protocol guarantee.
- Sustained unacked flooding dropped the BLE link twice during the benchmark
  session. Pace sends near the ~1.75 fps render cap rather than flooding as
  fast as the radio allows.
- **Design consequence**: an unacked full-frame path is worth roughly 40%
  more effective render rate plus non-blocking sends (~20 ms per frame vs
  ~740 ms acked), but real sustained animation on this hardware belongs to
  the **graffiti delta path** instead — `set_pixels`/`display.set_pixels` is
  unacked, ~20 ms per command, ≤255 pixels per command, roughly 50
  commands/second achievable. If you're animating a small changing region
  (a cursor, a sparkline, a clock's seconds digit) rather than the whole
  canvas, deltas are both faster and don't fight the frame-rate cap.

### Low-MTU panels on BlueZ

The transport trusts the write characteristic's reported
`max_write_without_response_size`. Some iDotMatrix panels on BlueZ
under-report this (around 20 bytes), which silently throttles unacked
writes into many tiny chunks. If you're on Linux/BlueZ and frames or GIF
uploads are much slower than expected, override the negotiated size:

```python
from pyidotmatrix import BleTransport

transport = BleTransport(mac_address=None, write_size_override=514)
```

The SDK doesn't do this automatically — a panel that genuinely only supports
a small MTU would break if writes were forced larger — so this is an opt-in
escape hatch, not a default.
