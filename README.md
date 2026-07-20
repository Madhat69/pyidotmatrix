# pyidotmatrix

Opinion-free, async-first Python SDK for iDotMatrix BLE pixel displays.
Licensed GPL-3.0-or-later — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

This project has two equally important goals:

1. **The definitive Python SDK** for iDotMatrix displays — controlling a
   panel should feel like controlling a device, not constructing packets.
2. **The reference implementation and documentation of the device protocol**
   — every verified reverse-engineering discovery lands here; every
   unverified one is clearly marked experimental. Protocol research is a
   first-class contribution (a good hardware probe log is worth as much as a
   feature).

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full architecture review,
capability inventory with evidence, and the path to 1.0.

> **Why `pyidotmatrix` and not `idotmatrix`?** The `idotmatrix` name on PyPI
> (and its import namespace) belongs to the incumbent library by derkalle4 —
> installing both would collide in site-packages. One name everywhere, zero
> collision (ROADMAP §14, decided 2026-07-20).

## Install

Not yet on PyPI. From a checkout:

```
pip install -e .          # library
pip install -e .[test]    # + test tooling
```

Requires Python 3.12–3.14. BLE via [bleak](https://github.com/hbldh/bleak)
(Windows/Linux/macOS).

## Protocol maturity at a glance

| Subsystem | Status |
|---|---|
| BLE transport (reconnect, acks, notifications) | ✅ hardware-proven |
| Framebuffer (DIY full frames + entry/quit modes) | ✅ |
| Graffiti (partial pixel updates) | ✅ |
| Images / GIF (adapt + native playback) | ✅ |
| Native clock | ✅ |
| Alarms (Timer slots, content + buzzer) | ✅ |
| Text (device-rendered) | ⚠ broken on 32×32 — fix in progress |
| Effects / color | ✅ (simplified vs vendor app) |
| Countdown / stopwatch / scoreboard | ⚠ source-confirmed |
| Weekly schedule | ⚠ partially verified |
| Music sync / eco / experimental | ⚠/❓ |

✅ hardware-verified · ⚠ experimental (source-confirmed, not verified) ·
❓ reverse engineering in progress. Full table with evidence: ROADMAP §3.

## Layers

```
protocol/   pure byte builders (no I/O), one per device feature
transport/  BLE connection lifecycle, chunked writes, reconnect supervision
display/    DisplayBackend interface + BleDisplay (hardware) and SimulatorDisplay
client.py   IDotMatrixClient — full-feature facade over one connection
imaging.py  canvas-fitting helpers (image adaptation)
```

The driver moves bytes to the device. It does not schedule, render app frames,
diff frames, or decide between full frames and pixel updates — those are caller
concerns.

## Two surfaces

**DisplayBackend** — the minimal frame pipeline seam (`show_frame`, `set_pixels`,
brightness, power). `BleDisplay` and `SimulatorDisplay` both satisfy it, so
callers are backend-agnostic.

```python
from pyidotmatrix import BleDisplay, BleTransport, ScreenSize, SimulatorDisplay

display = BleDisplay(ScreenSize.SIZE_32x32, BleTransport(mac_address=None))
await display.connect()
await display.show_frame(rgb_bytes)                 # full frame (32*32*3 bytes)
await display.set_pixels((0, 255, 0), [(1, 1)])     # partial update

sim = SimulatorDisplay(ScreenSize.SIZE_32x32, on_frame=lambda buf: ...)  # no hardware
```

**IDotMatrixClient** — the full native-feature facade; every device capability,
sharing one connection with `.display`.

```python
from pyidotmatrix import IDotMatrixClient, ScreenSize

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

**Protocol truth worth knowing:** an ack confirms *receipt*, not *effect* —
the device can accept a command and not act on it. The SDK documents these
cases rather than hiding them (see ROADMAP §4).

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

Protocol builders are covered by byte-exact golden tests. Hardware probes
live in `probes/` — human-run against a real panel, never in CI.

## Contributing

Reverse engineering is a first-class contribution: hardware probe results,
BLE packet captures, firmware/model comparisons, and protocol documentation
are as valuable as code. Start with `probes/` and the reverse-engineering
notes referenced throughout `docs/`.

## Credits

This SDK builds on the reverse-engineering lineage of
[8none1](https://github.com/8none1/idotmatrix),
[derkalle4](https://github.com/derkalle4/python3-idotmatrix-client) (GPLv3),
and [markusressel](https://github.com/markusressel/idotmatrix-api-client) —
see [NOTICE](NOTICE).
