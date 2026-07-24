# pyidotmatrix documentation

Start here if you're browsing `docs/` directly. The top-level
[README](../README.md) is the pitch and ten-line quick start; everything
below goes deeper.

## Using the SDK

| Page | What's in it |
|---|---|
| [Getting Started](getting-started.md) | Install → discover → connect → clock/text/gif/full frame, in ten lines. Start here if you're new. |
| [Feature Guide](features.md) | Every client namespace (`clock`, `text`, `gif`, `effect`, `graffiti`, alarms, ...) with usage examples and each feature's hardware-verification status. |
| [API Reference](api-reference.md) | Exact public signatures for every class and method — hand-curated from the source, not generated. |
| [Architecture](architecture.md) | The layer diagram (`protocol/` → `transport/` → `display/` → `client.py`) and why the driver is deliberately opinion-free. |

## The protocol, and what's actually known about it

This is the part of the project that's arguably more valuable than the code:
a dated, evidence-graded record of how the hardware actually behaves.

| Page | What's in it |
|---|---|
| [Protocol Notes](protocol-notes.md) | The doctrine every ⚠/✖-tagged feature is measured against: acks confirm receipt not effect, write-with-response as flow control, chunked-upload handshakes, per-mode persistence, endianness, Windows/WinRT resilience, and streaming/performance (the ~1.75 fps DIY-frame render cap, write-without-response, `write_size_override`). |
| [Hardware Compatibility](hardware-compatibility.md) | The full capability table — every command's verification status, evidence, and which panel it was tested on — plus how to extend it with your own hardware. |
| [Firmware Notes](firmware-notes.md) | What's known (and not known) to vary across panel sizes and firmware revisions. |
| [Reverse-engineering notes](reverse-engineering/) | The decompiled-APK analysis behind the protocol findings above: byte layouts, source citations, and which claims are hardware-confirmed vs. hypothesis. Start with its own [index](reverse-engineering/README.md). |
| [`docs/PROBE_PLAN.md`](PROBE_PLAN.md) | The open research questions currently worth hardware time, if you want to help push a ⚠/❓ row to ✅. |

## Project direction

| Page | What's in it |
|---|---|
| [ROADMAP.md](ROADMAP.md) | Full architecture review, capability inventory with evidence, and the milestone plan to 1.0. The authoritative source for *why* the API and repository look the way they do. |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | How to run the test suite, how to run hardware probes safely, and the ⚠→✅ graduation process for experimental features. |

## Evidence conventions

Every capability claim in this documentation is tagged with one of:

- ✅ **Verified** — observed doing the right thing on real hardware, probe/date cited.
- ⚠ **Source-derived** — byte layout confirmed from the decompiled vendor app, not (or not conclusively) exercised on hardware.
- ❓ **Unknown** — wire bytes exist but their meaning or effect is unestablished even in the app source.
- ✖ **Known-broken** — sent to real hardware and observed *not* working there.

These map onto `CapabilityStatus` in `pyidotmatrix/capabilities.py`, the
single machine-readable source every status tag in this documentation is
drawn from — see [Hardware Compatibility](hardware-compatibility.md) for the
full legend and the rendered table.
