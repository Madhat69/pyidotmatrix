# Firmware Notes

Everything hardware-verified in this SDK was tested against **one panel**: a
32×32 unit (name prefix `IDM-`), against vendor APK `v2.1.2 googleRelease
(2026-06-29)`. This page collects what's known to *vary* by panel
size/firmware — as opposed to [Hardware Compatibility](hardware-compatibility.md),
which is the full per-capability status table for the reference panel itself.

There is no runtime feature-probing in this SDK by design: the device acks
commands it doesn't act on, so asking the device "can you do X?" at runtime
would just get lied to. Compatibility knowledge here is built from evidence
only (probes + decompiled-source citations), the same as the capability
table — see
[Hardware Compatibility § How to extend this table](hardware-compatibility.md#how-to-extend-this-table)
if you have a panel that isn't 32×32.

## Known variation axes

| Variation | What's known | Evidence |
|---|---|---|
| Per-size text senders | The vendor app has five (`sendTextTo832/1616/3232/1664/6464`); this SDK ports two (`build_text_packet` generic, `build_text_packet_32x32`). 32×32 **rejects** (renders truncated on) the generic packet — it needs its own sender. Whether the other four sizes have the same generic-packet problem is unknown; nothing but 32×32 has been tested. | probe 2026-07-19; `pyidotmatrix/protocol/text.py` |
| Timer text font variant | The vendor app selects an 8-row vs 16-row font by `LedType` (implies panel-size-dependent text rendering for Timer/alarm text content, which itself is unmapped — see `experimental.timer_set` in the Feature Guide). | decompiled source only, unverified |
| Screen-timeout family | No ack and no visible effect at all on the reference 32×32 (`common.set_screen_timeout` / `read_screen_timeout`). Likely a feature this specific panel doesn't implement, not a universal protocol dead-end — units and support are otherwise unknown pending a panel that *does* respond. | probe 2026-07-12 |
| `set_time_indicator` | Bytes still shipped by the current official app, but the original research lab's notes describe it as "doesn't seem to work" on some models/firmware even from the app's own perspective — not an SDK-specific gap. | lab note + decompiled source |
| Graffiti header byte 3 | Only value `1` (the app's own hardcoded constant) draws on the reference panel; this is presented as a firmware/legacy quirk rather than a caller-facing option — the SDK doesn't expose it as a parameter. | probe 2026-07-21 |
| Persistence-by-mode-kind table | Effect and fullscreen color flash-persist across power-cycle; clock and DIY framebuffer never do. Documented in full in [Protocol Notes](protocol-notes.md#persistence-is-per-mode-kind) — recorded here because persistence behavior is exactly the kind of thing that could plausibly differ by firmware revision, though only one revision has been tested. | probes 2026-07-17 |
| Write-without-response | Honored by the reference panel (unacked frames render). LumiSync's independent reverse-engineering notes report it **ignored** on their unit — a real firmware-level difference, not a bug in either project's driver. | streaming benchmark 2026-07-20; see [Protocol Notes § Streaming](protocol-notes.md#streaming--performance) |
| BlueZ write-size under-reporting | Some iDotMatrix panels on Linux/BlueZ report a ~20-byte write size that's smaller than what they actually accept (~514 bytes usable). The SDK does not auto-correct this — see `write_size_override`. | community reports; see [Protocol Notes § Low-MTU panels](protocol-notes.md#low-mtu-panels-on-bluez) |

## Contributing a new panel's results

If you have a 16×16 or 64×64 panel (or a different 32×32 firmware revision),
the most valuable thing you can do is run the probe checklist against it and
report results — even negative ones. See
[Hardware Compatibility § How to extend this table](hardware-compatibility.md#how-to-extend-this-table)
and [CONTRIBUTING.md](../CONTRIBUTING.md). A single confirmed "this doesn't
work on my 64×64 either" turns a one-panel anecdote into a documented
protocol fact.

## Reverse-engineering evidence

The decompiled-APK research behind every claim above (and everything in
[Hardware Compatibility](hardware-compatibility.md)) lives in
[docs/reverse-engineering/](reverse-engineering/) — see its
[index](reverse-engineering/README.md) for what each document covers and how
it relates to the hardware probes in `probes/`.
