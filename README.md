# idotmatrix

Opinion-free Python driver for iDotMatrix BLE pixel displays. Part of the
GlanceOS monorepo; usable standalone. Licensed GPL-3.0-or-later.

## Layers

```
protocol/   pure byte builders (no I/O), one per device feature
transport/  BLE connection lifecycle, chunked writes, reconnect supervision
display/    DisplayBackend interface + BleDisplay (hardware) and SimulatorDisplay
client.py   IDotMatrixClient — full-feature facade over one connection
imaging.py  canvas-fitting helpers (used only for GIF adaptation)
```

The driver moves bytes to the device. It does not schedule, render app frames,
diff frames, or decide between full frames and pixel updates — those are caller
concerns.

## Two surfaces

**DisplayBackend** — the minimal frame pipeline seam (`show_frame`, `set_pixels`,
brightness, power). `BleDisplay` and `SimulatorDisplay` both satisfy it, so
callers are backend-agnostic.

```python
from idotmatrix import BleDisplay, BleTransport, ScreenSize, SimulatorDisplay

display = BleDisplay(ScreenSize.SIZE_32x32, BleTransport(mac_address=None))
await display.connect()
await display.show_frame(rgb_bytes)                 # full frame (32*32*3 bytes)
await display.set_pixels((0, 255, 0), [(1, 1)])     # partial update

sim = SimulatorDisplay(ScreenSize.SIZE_32x32, on_frame=lambda buf: ...)  # no hardware
```

**IDotMatrixClient** — the full native-feature facade; every device capability,
sharing one connection with `.display`.

```python
from idotmatrix import IDotMatrixClient, ScreenSize

client = IDotMatrixClient(ScreenSize.SIZE_32x32)
await client.connect()
await client.countdown.start(25, 0)        # e.g. a Pomodoro (device runs it natively)
await client.clock.show()
await client.text.show("HELLO", font_path=...)
await client.gif.upload_file("anim.gif")
await client.display.show_frame(rgb_bytes) # rendered frames, same connection
```

Feature namespaces: `chronograph`, `countdown`, `clock`, `scoreboard`, `eco`,
`color`, `graffiti`, `effect`, `music_sync`, `text`, `gif`, `common`, plus `display`.

### Device acknowledgements

The device pushes a status ack for every recognized command (accepted / rejected).
Observe them passively, or await one for a specific command:

```python
# passive: fires for every command's ack
unsubscribe = client.add_response_listener(lambda ack: print(ack.command_type, ack.accepted))

# active (opt-in): send a command and wait for its ack, or None on timeout
from idotmatrix.protocol import common
ack = await client.await_device_ack(common.build_set_brightness(60))
```

See [../docs/ROADMAP.md](../docs/ROADMAP.md) for the protocol details and remaining
reverse-engineering work.

### Lifecycle & observability

```python
client.set_auto_reconnect(True)              # arm/disarm reconnect at runtime
unsub = client.add_event_listener(print)     # write failures, reconnects
snap = client.snapshot()                     # address, connected, write_size, reconnect_count, last_failure
await client.show_image("photo.png")         # adapt to the screen and display
```

Listener registrations return an unsubscribe callable. A listener that raises is
isolated — it cannot break connection handling.

**Low-MTU panels:** the transport trusts the characteristic's reported write size.
Some iDotMatrix panels on BlueZ under-report it (~20 bytes); pass
`BleTransport(..., write_size_override=514)` for full-speed frames on those.

## Tests

```
pip install -e .[test]
pytest
```

Protocol builders are covered by byte-exact golden tests.
