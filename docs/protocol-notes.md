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
  reference panel: `device.freeze_screen`, `device.set_speed`,
  `experimental.set_time_indicator`, `music_sync.send_image_rhythm`. See the
  [Hardware Compatibility table](hardware-compatibility.md) for the specific
  evidence behind each.
- The inverse also happens: **`device.set_time` works and never acks at all.**
  Zero acks across seven RTC jumps, with schedules armed and unarmed alike, so
  the SDK sends it fire-and-forget rather than paying a 2 s ack timeout on
  every call. Don't wait on an ack for it, and don't read the silence as
  failure.

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

## Persistence and durability

Two kinds of device state live behind the same connection, and they persist by
completely different rules. Confusing them is the easiest way to silently lose
content you believe you wrote.

There is a second distinction underneath, and it is worth getting straight
before reading the rest of this section. For *display* content the panel keeps
**three separate things**, and they routinely disagree:

| | survives a BLE reconnect? | survives a power cycle? |
|---|---|---|
| **The stored GIF payload** | yes | **yes** — the device still recognizes its CRC |
| **The active display mode** | reasserts — this is what a reconnect restores | no |
| **The flash / boot display state** | *not* what a reconnect restores | **yes** — the panel boots into it |

All three were observed holding different content at the same moment. So "this
colour stayed up for three days across power cycles" and "this colour vanished
on a reconnect" are both true and describe different states: the first is the
boot state, the second is the active mode reasserting.

### Config-class state — durable immediately

Brightness, the RTC (`device.set_time`), eco windows, alarms (Timer slots) and
weekly schedules are **flash-backed and committed on any connection**. They
survive a clean disconnect, a software power cycle, and a physical mains power
cut — an unplugged panel boots back with the brightness it was last given and
fires the alarms it was last armed with. Set them once at startup; nothing
needs to protect them.

Config-class state is also *inherited*: a fresh client can connect to a panel
already carrying an eco window or an armed alarm that it never set and cannot
read back.

### Display-class state — lazily persisted, and losable

Which content the panel is *showing* (clock, GIF, text, fullscreen colour,
effect, DIY frame) is held in RAM when first written and committed to flash
**lazily**. A clean BLE disconnect makes the device revert to its **last
persisted** mode — usually the clock.

Everything in this subsection answers one specific question: **does the
active display mode survive a BLE reconnect?** That is a different question
from "does a physical power cut lose my write?", which has its own, much
smaller number — see
[The flash commit: surviving a power cut](#the-flash-commit--surviving-a-power-cut)
below. Keep the two apart; conflating them cost the lab two days of confused
probing before the numbers below were sorted into the right buckets.

**The practical rule: if you write content and disconnect immediately, expect
to lose it.** The write is acked, the SDK reports success, and the panel
reverts anyway. There is no error to catch and nothing the driver can do about
it.

Content survives a disconnect if **either** of the following holds. Each is
independently sufficient; neither is required.

- **Dwell** — enough time has passed since the write, in a session that has not
  reconnected. Measured on a ladder: 8, 30, 60, 75, 90 and 100 seconds all
  died; 180 seconds survived. **Allow about 3 minutes.** The exact threshold
  inside that band is not known and is not worth pinning down — don't design
  against a precise number.
- **A prior disconnect/reconnect earlier in the same session** — a client that
  has already reconnected once protects everything it writes afterwards, even
  only ~10 s later. Shown for GIFs (twice) and for fullscreen colour. The
  mechanism is unexplained. The effect is per-process: another process's
  earlier reconnect does not help you.

**Practical guidance: allow roughly 3 minutes before disconnecting, or
reconnect once first.** The second is far cheaper — ten seconds of protection
beats a hundred seconds of waiting — so if a program must write and hand off
quickly, do a throwaway connect/disconnect/reconnect before the real write.
Otherwise, dwell.

One trap, if you ever try to verify any of this yourself: putting different
content on screen does **not** persist it. Activating a stored GIF, for
instance, changes the active mode while leaving the flash state untouched —
even after minutes on screen. To test whether a write survived, the *persisted*
state has to differ from what you wrote, which costs a full commit period to
set up.

Multiple clients *can* share a panel without one stealing the other's content,
but the reason is dwell, not ownership — there is no per-client scoping in
this firmware.

### The flash commit — surviving a power cut

Separate question, separate clock. Everything above is about the *active
display mode* reasserting after a **BLE reconnect**. This section is about
whether a write is actually in flash before a **power cut** — pulling the
plug, not just dropping the link.

**Settled 2026-07-29 (`probes/probe_p19_g10_advert_watch.py` through
`probe_p19_g12_*.py`): the commit runs on wall-clock time from the write,
5 s < t ≤ 10.3 s, and the BLE link state — connected, cleanly disconnected, or
yanked mid-session — does not matter.** The instrument that made this
measurable: the panel advertises at ~9 Hz whenever it's powered and *not*
connected, so a BLE scanner left running after the disconnect sees the power
cut arrive, pinning it to the last advertisement (~110 ms typical, ~2.1 s
worst case). That turns an otherwise-uncontrolled interval (the operator's own
reaction time pulling the plug) into a measured one.

| Trial | Write → power cut | Clean disconnect first? | Committed? |
|---|---|---|---|
| G12 yellow | < 5 s | yes | no |
| G12 magenta | ~10.3 s | yes | yes |
| G11 white | 47.9 s (only 2.1 s of that connected) | yes | yes |
| G12 cyan | ~69 s | no — the plug killed a live link | yes |

The white and cyan rows are what make this a wall-clock result rather than a
dwell result: white committed after only 2.1 s of link-up time, and cyan
committed with no clean teardown at all. Neither time-connected nor a clean
disconnect is required — only elapsed time since the write.

**Do not quote the 100–180 s dwell figure above for power-cut durability — it
answers the reconnect question, not this one.** A reconnect can only read the
*active display mode*; only a power cycle reads *flash*. Two probe sessions
conflated the two before this was sorted out; see `docs/PROBE_PLAN.md` P19
"THE FLASH COMMIT" for the full account, including which earlier readings that
retracts.

**Caller guidance: leave about 15 seconds between your last write and any
power loss, connected or not, and the content is in flash.**

### Recovery: re-activate, don't re-transfer

When a GIF is lost this way, **only the current-mode pointer is gone — the
stored payload is not**. The device still holds the upload and recognizes its
CRC:

```python
await client.gif.activate_stored(gif_bytes)   # True — restored, nothing transferred
```

You hand it the same bytes only so the device can match their CRC; nothing is
re-uploaded. The caveat is that this only works for content
with a re-activate path; a parked DIY frame has no equivalent command, so a
lost frame has to be re-sent.

### Per-mode notes

| Mode kind | Survives clean disconnect | Survives power-cycle |
|---|---|---|
| Effect | ✅ once persisted | ✅ (observed surviving 3 days) |
| Fullscreen color | ✅ once persisted | ✅ |
| GIF / text | ✅ once persisted; otherwise recoverable with `activate_stored()` | payload ✅, mode pointer follows the lazy rule |
| Clock | reverts to the clock — undetectable either way | ❌ |
| DIY framebuffer | ❌ (reverts in ~2 s) — **unless** quit mode 2 (keep-frame) was used, in which case the kept frame survives a clean disconnect | ❌ (never) |

"Once persisted" in the table above means the flash commit has had time to
run — see
[The flash commit: surviving a power cut](#the-flash-commit--surviving-a-power-cut):
allow ~15 s, not the ~3 minutes the reconnect-dwell figure above might suggest.
The two clocks are unrelated.

*How* a connection ends also matters: a clean disconnect reverts an unparked
DIY frame within about 2 seconds; an abrupt link loss (radio drop, crash)
freezes the last frame on screen indefinitely instead.

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
  unacked, ~20 ms per command, ≤255 pixels per command, so roughly 50
  commands/second is the theoretical rate (measured ceiling below). If you're
  animating a small changing region (a cursor, a sparkline, a clock's seconds
  digit) rather than the whole canvas, deltas are both faster and don't fight
  the frame-rate cap.

### What you can actually sustain for minutes

The benchmark above found the *ceilings*. A separate ten-minute endurance run
(`probes/probe_p4_streaming_endurance.py`, 2026-07-28, reference 32×32 panel)
found the rates that hold steady without back-pressure. **These are the numbers
to design an animated scene against:**

| What you're sending | Safe sustained rate | Measured |
| --- | --- | --- |
| Unacked full frames | **1.5 fps** | 900 frames over 600 s, exact pacing, 900 acks, zero missed slots, zero reconnects |
| Graffiti deltas (255 px/command) | **40 commands/s** | 10, 20 and 40 cmd/s each exact for 30 s with zero missed slots |

1.5 fps sits deliberately just under the ~1.75 fps render cap and held for the
full ten minutes with no decay at all. For deltas, 40 cmd/s is clean; pushing to
60 cmd/s only achieved **55 cmd/s** and started missing pacing slots, so treat
~55/s as a hard ceiling you should not plan to live at.

> **⚠ Mixing deltas into a frame stream costs you frame acks.**
> Streaming full frames alone, every frame came back with an fa03 notification —
> a 1.00 ack-to-frame ratio over ten minutes. Interleaving graffiti deltas with
> those frames (1 fps + 10 deltas/s for five minutes) dropped that ratio to
> **0.73** — 218 acks for 300 frames — with a shorter run corroborating at 0.87.
> Sends and pacing were unaffected; only the acks thinned out.
>
> That matters because the fa03 ack is the device telling you a frame was
> *processed*, and it's the free flow-control signal this SDK gives you. If you
> design a delta-driven animation with periodic full-frame keyframes and pace
> yourself on frame acks, expect roughly a quarter fewer of them than a
> pure full-frame stream would give you — don't treat a missing ack in mixed
> mode as a dropped frame or a dead link. The mechanism is unknown; this is a
> measurement, not an explanation.

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
