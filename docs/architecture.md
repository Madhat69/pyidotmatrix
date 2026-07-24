# Architecture

## Layers

```
protocol/   pure byte builders (no I/O), one module per device feature
transport/  BLE connection lifecycle, chunked writes, reconnect supervision
display/    DisplayBackend interface + BleDisplay (hardware) and SimulatorDisplay
client.py   IDotMatrixClient -- full-feature facade over one connection
imaging.py  canvas-fitting helpers (image adaptation)
```

Each layer only talks to the one below it:

- **`protocol/`** (`pyidotmatrix/protocol/*.py`) builds command bytes from
  typed arguments. No BLE, no asyncio, no state — `build_show(style, colors)`
  in, `bytearray` out. This is also where the reverse-engineering evidence
  lives closest to the code: builder docstrings cite the APK source and the
  probe that hardware-verified (or falsified) a byte's meaning. Byte-exact
  golden tests pin every builder (`tests/test_protocol_*.py`).
- **`transport/`** (`pyidotmatrix/transport/ble.py`) owns one `BleakClient`:
  connect/reconnect, chunked writes at the negotiated MTU, ack correlation
  (`await_device_ack`), and observability (`snapshot()`, event listeners). It
  has no idea what a "clock" or a "gif" is — it moves bytes and reports what
  happened.
- **`display/`** (`pyidotmatrix/display/`) is the minimal frame-pipeline
  seam: `show_frame`, `set_pixels`, brightness, power. `BleDisplay` (real
  hardware) and `SimulatorDisplay` (in-memory) both satisfy the
  `DisplayBackend` protocol, so a caller can render against either without an
  `if hardware:` branch anywhere in its own code.
- **`client.py`** is the full-feature façade: one `IDotMatrixClient` per
  device connection, exposing every native mode as a namespace
  (`.clock`, `.text`, `.gif`, `.effect`, ...) plus `.display` for the raw
  framebuffer, all sharing the same `BleTransport`.

## Why opinion-free

The driver's job stops at "move these bytes to the device and tell you what
came back." It deliberately does **not**:

- schedule frames or pick a frame rate,
- diff frames to decide between a full `show_frame` and a `set_pixels` delta,
- own application-level render state (a scene graph, a compositor, a "what's
  currently on screen" model beyond the one `_diy_mode_enabled` bit needed to
  satisfy the device's own DIY-mode-entry protocol requirement),
- retry a rejected command with different arguments, or silently paper over
  a firmware quirk.

That's a deliberate boundary, not an oversight: those decisions are
caller-specific (a game wants a different render loop than a clock daemon),
and baking one caller's policy into the driver would make it wrong for every
other caller. The driver's contract is narrower and more durable: given valid
protocol arguments, send exactly the bytes the protocol requires, correlate
the device's own response, and report both faithfully — including when the
device's response is a lie (an ack that doesn't mean "it worked"; see
[Protocol Notes](protocol-notes.md#acks-confirm-receipt-not-effect)).

One concrete consequence: `BleDisplay` tracks a single bit of state
(`_diy_mode_enabled`) purely because entering DIY mode before a frame is a
*protocol* requirement (the device must be told to expect framebuffer writes),
not because the driver has an opinion about when frames should be sent. A
caller that also drives native modes on the same connection (clock, text,
effects) is responsible for telling the display object when something else
took the panel out of DIY mode (`invalidate_diy_mode()`) — the driver has no
visibility into commands sent through other namespaces on the same transport.

## Two surfaces, one connection

`DisplayBackend` and `IDotMatrixClient` aren't alternatives — `client.display`
*is* a `BleDisplay`. Pick your entry point:

- Only need the pixel surface (frame pipeline, no native modes)? Use
  `BleDisplay`/`SimulatorDisplay` directly and stay backend-agnostic.
- Need native modes too (alarms, effects, clock, text)? Use
  `IDotMatrixClient`; `client.display` gives you the same frame pipeline on
  the same connection.

## Protocol module inventory

One builder module per device feature, all pure functions:

`chronograph` `clock` `common` `countdown` `eco` `effect` `fullscreen_color`
`gif` `graffiti` `image` `music_sync` `schedule` `scoreboard` `text` `timer`,
plus shared primitives in `bytes_.py` (chunking, length prefixes, CRC32) and
the shared ack/status decoder in `response.py`.

See the [Feature Guide](features.md) for how each maps onto a client
namespace, and the [Public API Reference](api-reference.md) for exact call
signatures.
