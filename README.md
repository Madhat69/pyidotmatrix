# pyidotmatrix

[![CI](https://github.com/Madhat69/pyidotmatrix/actions/workflows/ci.yml/badge.svg)](https://github.com/Madhat69/pyidotmatrix/actions/workflows/ci.yml)

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

## Documentation

| | |
|---|---|
| [Getting Started](docs/getting-started.md) | Install → discover → connect → clock/text/gif/full frame, ten lines. |
| [Feature Guide](docs/features.md) | Every namespace, with usage examples and hardware-verification status. |
| [Hardware Compatibility](docs/hardware-compatibility.md) | The full capability table, and how to extend it with your own panel. |
| [Protocol Notes](docs/protocol-notes.md) | Acks vs. effect, chunking, persistence, endianness, streaming/performance — the SDK's moat. |
| [Architecture](docs/architecture.md) | The layer diagram and why the driver is opinion-free. |
| [API Reference](docs/api-reference.md) | Exact public signatures. |
| [Firmware Notes](docs/firmware-notes.md) | What's known to vary across panel sizes/firmware. |
| [Reverse-engineering notes](docs/reverse-engineering/) | APK decompile analysis behind the protocol findings above. |

Full doc index: [docs/README.md](docs/README.md).

Runnable examples: [examples/](examples/) — discovery, images, animation, graffiti, GIFs, native widgets, the simulator, and the capability table, as standalone scripts.

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
| Framebuffer (DIY full frames + entry/quit modes) | ✅ (device renders full frames at a hard ~1.75 fps; unacked/without-response writes honored) |
| Graffiti (partial pixel updates + h/v mirror) | ✅ header fully mapped 2026-07-21 |
| Images / GIF (adapt + native playback) | ✅ |
| Native clock · countdown · stopwatch · scoreboard | ✅ |
| Text (device-rendered, per-panel-size builders) | ✅ verified on 32×32 |
| Alarms (Timer slots: GIF + PNG content, buzzer, week-day mask) | ✅ incl. week-bit mapping |
| Eco (scheduled dim) · screen flip | ✅ |
| Effects / color | ✅ activation; ⚠ the vendor app's speed dial works but its wire path is unmapped |
| Weekly schedule | ⚠ partially verified |
| Music sync | ✖ acked but no visible behavior on the reference panel |
| freeze / set_speed / time indicator | ✖ acked, proven inert on the reference panel |

✅ hardware-verified · ⚠ experimental / partially mapped · ✖ known-broken on
the reference 32×32 (an ack confirms *receipt*, not *effect*). Every entry
carries machine-readable evidence:

```python
from pyidotmatrix import capability
capability("text.show").status        # CapabilityStatus.VERIFIED
capability("common.set_speed").evidence  # cites the probe and date
```

Full table with evidence: [pyidotmatrix/capabilities.py](pyidotmatrix/capabilities.py)
and ROADMAP §3.

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
from pyidotmatrix import IDotMatrixClient, ScreenSize, discover

devices = await discover()                     # [DeviceInfo(name='IDM-...', address=..., rssi=...)]
async with IDotMatrixClient.connect_to(devices[0], ScreenSize.SIZE_32x32) as client:
    await client.countdown.start(25, 0)        # e.g. a Pomodoro (device runs it natively)
    await client.clock.show()
    await client.text.show("HELLO", font_path=...)
    await client.gif.upload_file("anim.gif")
    await client.display.show_frame(rgb_bytes) # rendered frames, same connection
```

Commands are verified by default: a device rejection raises
`CommandRejectedError` (opt out with `verify_commands=False`).

Feature namespaces: `chronograph`, `countdown`, `clock`, `scoreboard`, `eco`,
`color`, `graffiti`, `effect`, `music_sync`, `text`, `gif`, `common`, plus `display`.
Alarms and weekly schedules live under `experimental` (bytes confirmed,
hardware-verified for the core paths, but not yet promoted out of that
namespace) — see the [Feature Guide](docs/features.md#experimental--unverified-andor-destructive).

### Device acknowledgements

The device pushes a status ack for every recognized command (accepted / rejected).
Observe them passively, or await one for a specific command:

```python
# passive: fires for every command's ack
unsubscribe = client.add_response_listener(lambda ack: print(ack.command_type, ack.accepted))

# active (opt-in): send a command and wait for its ack, or None on timeout
from pyidotmatrix.protocol import common
ack = await client.await_device_ack(common.build_set_brightness(60))
```

**Protocol truth worth knowing:** an ack confirms *receipt*, not *effect* —
the device can accept a command and not act on it. The SDK documents these
cases rather than hiding them (see [Protocol Notes](docs/protocol-notes.md)
and ROADMAP §4).

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
Streaming/animation performance (the ~1.75 fps DIY-frame render cap, why
deltas beat full frames for sustained animation): see
[Protocol Notes § Streaming & performance](docs/protocol-notes.md#streaming--performance).

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
are as valuable as code. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to
run the test suite, how to run hardware probes safely, and the ⚠→✅
graduation process for experimental features.

## Credits

This SDK builds on the reverse-engineering lineage of
[8none1](https://github.com/8none1/idotmatrix),
[derkalle4](https://github.com/derkalle4/python3-idotmatrix-client) (GPLv3),
and [markusressel](https://github.com/markusressel/idotmatrix-api-client) —
see [NOTICE](NOTICE).
