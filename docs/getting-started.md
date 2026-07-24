# Getting Started

Zero to a picture on the panel. Every call below is awaited inside an
`asyncio` coroutine — wrap the snippets in `asyncio.run(main())` if you're
pasting into a script.

## 1. Install

Not yet on PyPI (see [Release milestones](ROADMAP.md#17-release-milestones)).
From a checkout:

```
pip install -e .
```

Requires Python 3.12–3.14. BLE goes through
[bleak](https://github.com/hbldh/bleak), so Windows, Linux (BlueZ), and macOS
all work — see [Protocol Notes](protocol-notes.md#low-mtu-panels-on-bluez) if
you're on BlueZ and frames come out slow.

## 2. Discover

```python
from pyidotmatrix import discover

devices = await discover()   # scans for BLE advertisers named "IDM-*"
print(devices)                # [DeviceInfo(name='IDM-A03EAF', address='6D:FD:...', rssi=-52)]
```

No panel in range yet? `devices` is just an empty list — `discover()` doesn't
raise. If you already know the MAC address, skip discovery entirely; every
connect path below also accepts a bare address string.

## 3. Connect

`IDotMatrixClient` is the full-feature façade: one BLE connection shared
between native device modes (clock, text, effects, alarms, ...) and the raw
framebuffer (`.display`). Use it as an async context manager so disconnect
happens even if something raises:

```python
from pyidotmatrix import IDotMatrixClient, ScreenSize

async with IDotMatrixClient.connect_to(devices[0], ScreenSize.SIZE_32x32) as client:
    ...  # connected here; disconnects on exit, including on exceptions
```

`ScreenSize` must match your physical panel (`SIZE_16x16` / `SIZE_32x32` /
`SIZE_64x64`) — the driver has no way to ask the device its own size yet
(ROADMAP §16.3), so a mismatch produces garbage frames with no error.

You can also construct directly from a MAC string, without discovery:

```python
async with IDotMatrixClient.connect_to("6D:FD:00:11:22:33", ScreenSize.SIZE_32x32) as client:
    ...
```

## 4. The ten-line quick start

Discovery → connect → native clock → device-rendered text → a GIF → a raw
framebuffer frame, all on one connection:

```python
from pyidotmatrix import discover, IDotMatrixClient, ScreenSize

async def main():
    devices = await discover()
    async with IDotMatrixClient.connect_to(devices[0], ScreenSize.SIZE_32x32) as client:
        await client.clock.show()                                   # native clock face
        await client.text.show("HELLO", font_path="/path/to/font.ttf")
        await client.gif.upload_file("nyan.gif")                    # chunked upload + native playback
        await client.show_image("photo.png")                        # adapt + full framebuffer frame
```

Each call above *replaces* what's on screen — the device has one active mode
at a time (clock, text, effect, or DIY framebuffer). That's a firmware
property, not an SDK limitation; see
[Protocol Notes § Persistence](protocol-notes.md#persistence-is-per-mode-kind).

## 5. Rejections are loud by default

A device that nacks a command (e.g. an out-of-range brightness) raises
`CommandRejectedError` — the client awaits the fa03 ack for every command by
default (`verify_commands=True`). Turn it off for latency-sensitive or
best-effort sends:

```python
from pyidotmatrix import CommandRejectedError

try:
    await client.common.set_brightness(150)   # out of range
except CommandRejectedError as ex:
    print("device rejected it:", ex)

client.set_command_verification(False)   # fire-and-forget from here on
```

Read why this matters before you turn it off:
[Protocol Notes § Acks confirm receipt, not effect](protocol-notes.md#acks-confirm-receipt-not-effect).

## 6. What next

- **[Feature Guide](features.md)** — every namespace (`clock`, `text`, `gif`,
  `effect`, `graffiti`, alarms, ...), with usage examples and each feature's
  hardware-verification status.
- **[Hardware Compatibility](hardware-compatibility.md)** — the full
  evidence-backed capability table, and how to extend it with your own panel.
- **[Protocol Notes](protocol-notes.md)** — the doctrine every ⚠ feature in
  this SDK is measured against: acks, chunking, persistence, endianness,
  streaming/performance.
- **[Architecture](architecture.md)** — the layer diagram, if you're
  embedding this in something bigger than a script.
