*Migrated from the GlanceOS research lab, 2026-07-20. Historical evidence document — paths referenced inside may describe the original lab layout.*

# Alarm & Buzzer: APK Reverse-Engineering Map

Source: decompiled `com.tech.idotmatrix` APK at
`C:\Users\Madhat\Downloads\com.tech.idotmatrix.apk_Decompiler.com\sources\com\tech\idotmatrix\`
(package version string found in bytecode: `iDotMatrix_2026_06_29_19_07-v2.1.2_googleRelease`).

This is a **map for verification work**, not a finished port. Byte offsets below were
read directly from decompiled source, but the decompiler (jadx) aggressively reuses
and renames local variables under obfuscation — a few offsets in the most complex
methods (`ScheduleAgreement.textSolve`) could not be trusted at a glance and are
flagged. Verify every byte layout against the real device (fa03 ack: `01` sent =
accepted, `00`/silence = rejected/unrecognized — see `idotmatrix.protocol.response`
in the driver) before porting anything into `idotmatrix/protocol/`.

## Headline finding: `setAlarmClock()` is dead, upstream's "issue #18" lead is a dead end

`ble/BleProtocolN.java` lines 20-24:
```java
public static void setAlarmClock() {
}
public static void setTimeIndicator() {
}
```
Both are **empty stubs** — no bytes, never called anywhere in the app (confirmed via
whole-package grep). `bean/AlarmClock.java` (a data class with hour/min/second/flag/
type/data fields) is likewise **referenced nowhere** outside itself and the empty
stub file. This whole path is scaffolding for a feature that was never wired up.
**Do not spend time here.**

## The real feature: two independent systems, both already fully implemented in the app

### 1. Timer ("Add alarm" in the UI) — `core/data/TimerAgreement.java`

One-shot/per-day alarms, up to **10 slots** (`res/values/strings.xml`:
`alarm_clock_tips` = "Up to ten alarms can be added"). Each alarm shows a custom
image/GIF/text on the panel for a chosen duration when it fires, optionally with
the buzzer.

Backing bean: `core/db/bean/Timer.java` — fields: `num` (0-9, slot index), `week`
(bitmask, see below), `hour`, `min`, `type` (0/1/2 = image/gif/text — see content-type
table), `timeDuration` (1-4, maps to a fixed duration table), `buzzerEnable` (bool),
`imgData`/`imgUrl`/`materialJson`.

**Enable/update an alarm** — `TimerAgreement.sendData(...)`, three overloads (raw
image bytes / `Material` text at 16-row font / `Material` text at 8-row font via
`sendData832` for a different panel variant). All three build the same 24-byte
header, then CRC32 + 4096-byte chunking + 509-byte BLE packetization (**identical
structure to the already-ported GIF pipeline** — same `getSendData4096`/`getSendData`
pair, byte-for-byte the same chunking constants).

24-byte header (`TimerAgreement.java` lines ~127-166, the `sendData(BleDevice, Timer,
byte[], int, ...)` overload — the cleanest of the three to read):

| Offset | Field | Source |
|---|---|---|
| 0-1 | packet length (chunk + 24), big-endian short | `ByteUtils.short2Bytes` |
| 2 | `0x00` | constant |
| 3 | `0x80` | constant (`ByteCompanionObject.MIN_VALUE` = -128 = 0x80) |
| 4 | `timer.num` (0-9) | slot index |
| 5 | `timer.week` | bitmask, unpatched (see Schedule's `patch()` below — Timer does NOT call patch) |
| 6 | `timer.hour` | |
| 7 | `timer.min` | |
| 8-9 | duration, big-endian short | see duration table below |
| 10 | content type `i` (1/2/3) | passed in by caller, NOT `timer.type` directly — see content-type table |
| 11 | `1` if `timer.buzzerEnable` else `0` | **the buzzer flag** |
| 12 | `0` on first chunk, `2` on continuation | chunk-continuation flag, same pattern as DIY/GIF |
| 13-16 | total payload length, little-endian int | `ByteUtils.int2byte` |
| 17-20 | CRC32 of payload, little-endian int | `CrcUtils.CRC32.CRC32` = standard `java.util.zip.CRC32`, **same as our `binascii.crc32`** — no conversion needed |
| 21-22 | `0, 0` | constant |
| 23 | `timer.num + 20` | a second marker, purpose unclear — possibly a device-side content slot ID distinct from byte 4's timer-list slot |
| 24+ | payload (image/gif bytes, or the 14-byte text-metadata + bitmap stream — same layout as the already-ported `protocol/text.py`) | |

**Disable an alarm without deleting it** — `TimerAgreement.sendCloseData(...)`
(lines 182-225): a **flat 12-byte packet**, no chunking, no payload:
```
[len_lo, len_hi=0, 0x00, 0x80, num, week, hour, min, dur_lo, dur_hi, contentType, buzzerFlag]
```
Called from `ui/timer/TimerActivity.java:215` when the per-alarm list toggle is
switched off, with content-type hardcoded to `1` regardless of the alarm's real
type (likely irrelevant for a disable operation — verify).

**Content-type byte (offset 10) mapping**, confirmed from two call sites
(`ui/timer/AddTimerDialog.java:655-671` and `ui/timer/TimerActivity.java:194-211`,
both switch on `type`/`curMaterialType` 0/1/2 and pass a *different* literal as
the protocol byte):

| UI `type` | protocol byte 10 | meaning |
|---|---|---|
| 0 | **2** | static image |
| 1 | **1** | GIF |
| 2 | **3** | text (uses `sendData832` instead of `sendData` when `AppData.getLedType() == 2`, a different panel/font variant) |

**Duration table** (UI labels confirmed at `AddTimerDialog.java:572-583`, values in
seconds, big-endian short at header offset 8-9):

| `timer.timeDuration` | seconds | UI label |
|---|---|---|
| (unset/0, fallback) | 10 | "10s" |
| 1 | 30 | "30s" |
| 2 | 60 | "1min" |
| 3 | 300 | "5min" |
| 4 | 900 | "15min" |

This is how long the alarm's custom content stays on screen when triggered — **not**
the same field as the GIF module's `time_sign` (which we already ported in
`protocol/gif.py`); the two features reuse the same four duration buckets by
convention/coincidence, don't conflate them.

**Response parsing** (`TimerAgreement.parseDataNextPackage` /`parseDatasave`/
`parseDatafail`, lines 636-653) reads notifications of shape
`[_, 0, 0, 0x80, status]` — status `1` = next-chunk-please / `3` = fully saved /
`0` = failed. **This is a different, richer ack vocabulary than our fa03 `DeviceAck`
(which only has type/subtype/accept-reject)** — worth checking whether these are
still delivered on today's firmware over the same `fa03` notify characteristic, or
a different one. If the same characteristic, our `parse_response` will currently
mis-parse or ignore these (structure is `[cmd_type=0, cmd_subtype=0, status]` at a
different offset than our `[0x05,0x00,type,subtype,status]` — **needs a live
capture to reconcile**, don't assume compatibility.

**Open question, needs hardware verification**: swipe-to-delete in
`TimerActivity.java` (line 90, `getTimerDao().delete(...)`) is a **pure local
database removal — no BLE call is made**. Deleting a still-*enabled* alarm without
first toggling it off may leave a "ghost" alarm active on the device with no local
record of it. Verify by: enable an alarm, delete it via swipe (skip the disable
toggle), wait for it to fire, see if the panel still shows/buzzes it.

### 2. Schedule ("Weekly Schedule" themes) — `core/data/ScheduleAgreement.java` (Kotlin, compiled to Java)

Recurring weekly themes (breakfast/lunch/etc. — see `afternoon_tea` string), each
with a day-of-week bitmask + start/end time window, optional buzzer, and image/gif/
text content — same content trio as Timer but a different wire format (23-byte
header instead of 24, and no per-item duration — it's an active *window*, not a
one-shot display duration).

Backing beans: `core/db/bean/Schedule.java` (top-level: `enable`, `buzzerEnable`,
`scheduleThemeList`), `core/db/bean/ScheduleTheme.java` (`week`, `startHour`,
`startMin`, `endHour`, `endMin`, `type` 0/1/2 = image/gif/text, `imgData`).

**Master on/off** — `ScheduleAgreement.masterSwitch(enable, buzzer)` (line 600-606):
a **single 5-byte command**, not chunked:
```
[5, 0, 7, 0x80, packedByte]
```
where `packedByte` is built by `ByteUtils.getByteByArray({enable, buzzer, 0,0,0,0,0,0})`
— an 8-bit-to-1-byte packer reading the array **in reverse order** (see
`ByteUtils.getByteByArray`/`bitToByte`, `com/tech/idotmatrix/util/ByteUtils.java` —
note this is the **app-local** `ByteUtils`, a different class from
`com/tiro/jlotalibrary/util/ByteUtils` used elsewhere; both exist, don't confuse
them). Ack parsed by `verifyMasterSwitch` (line 609-617): `[5,0,7,0x80,status]`,
status echoed in byte 4 — **this matches our existing fa03 `DeviceAck` shape
exactly** (type=7, subtype=0x80), unlike Timer's ack format above.

**Per-theme upload** — three near-identical methods, all building a **23-byte
header** (one byte shorter than Timer's 24 — no buzzer byte in the per-theme
header; buzzer is set once via `masterSwitch`, not per-theme):

- `gifSolve` (lines 229-276) — cleanest to read, use as the reference:
  ```
  [len_lo, len_hi, 5, 0x80, index, patch(week), startHour, startMin, endHour, endMin,
   1, (0|2 continuation), totalLen_le×4, crc32_le×4, 0, 0, index+30]
  ```
  Header byte 2 = `5` (constant — this is the Schedule-family "type", analogous to
  Timer's `0x00` and the plain-GIF module's `1`), byte 10 = `1` fixed for gif.
  Trailing marker is `index + 30` (vs. Timer's `num + 20` — the two features use
  disjoint marker ranges, possibly a device-side content-slot ID space shared
  across features; worth checking whether other features also claim ranges, e.g.
  DIY frames claim what offset).
- `imageSolve2` (lines 515-568) — identical layout, byte 10 = `2` instead of `1`.
- `textSolve` (lines 278-487) — **do not trust the byte offsets read directly off
  this method**; jadx's obfuscated-variable output reuses `char c`, `c2`...`c10` as
  aliases for plain ints across branches in a way that is very easy to misread by
  eye. The *structural* shape (23-byte header + CRC + text metadata/bitmap payload,
  same as `gifSolve`/`imageSolve2` but byte 10 = `3`) is almost certainly right by
  analogy, but **re-derive this one from a live BLE capture rather than the
  decompiled source** — don't hand-transcribe it.

**`patch(week)`** (lines 218-227): takes the raw week bitmask, converts to an
8-char binary string, drops the MSB, appends `"1"`, reparses as binary. Net effect
looks like a left-rotate-by-one with a forced low bit — **verify empirically**
(build a table of week-checkbox-selection → raw `week` int → `patch()` output → what
day the schedule actually fires on, by testing against the device) rather than
trusting a hand-derivation of the bit-twiddling.

**Per-theme ack** — `verifySetup` (line 620-628): `[5,0,5,0x80,status]`
(note: type=**5**, matching the per-theme header's byte 2, not the master-switch's
type=7). Status `1` = proceed to next queued chunk, `3` = fully saved, else = error
(`onError` codes 10011/10012/10013 are app-internal, not device bytes).

## What's genuinely new vs. what we already have

- **Chunking (4096-byte outer, 509-byte BLE inner, CRC32-guarded)** — identical
  pattern to our already-ported `protocol/gif.py` / `protocol/image.py`. No new
  transport-layer work; both features can likely reuse
  `idotmatrix.protocol.bytes_` and `idotmatrix.transport.ble.BleTransport.write_packets`
  as-is once the header-building functions are written.
- **New**: the 24-byte (Timer) and 23-byte (Schedule) headers themselves, the
  flat non-chunked `sendCloseData` (12 bytes) and `masterSwitch` (5 bytes) commands,
  and the `patch()` week-bitmask transform.
- **New ack vocabulary**: Timer's `[_,0,0,0x80,status]` 1/3/0 three-way status is
  unlike anything currently in `protocol/response.py` (which only knows
  accept/reject). Schedule's acks (`[5,0,7,0x80,·]` / `[5,0,5,0x80,·]`) **do** fit
  the existing `DeviceAck` shape.

## Suggested verification order for Fable

1. **Schedule master switch first** — smallest, flattest command (5 bytes), ack
   shape already matches our `DeviceAck`/`parse_response`. Confirms endianness/CRC
   assumptions transfer before touching anything chunked.
2. **Timer `sendCloseData`** — 12 bytes, flat, no chunking, no payload. Second-
   smallest surface.
3. **Timer `sendData` (image variant)** — reuse the GIF chunking code path,
   swap in the 24-byte header. Watch the panel for a custom alarm image + confirm
   buzzer byte 11 actually buzzes.
4. **Schedule `gifSolve`/`imageSolve2`** — 23-byte header, same idea.
5. **Schedule `textSolve`** — re-derive the header from a live capture rather than
   the decompiled source, per the warning above.
6. Reconcile the Timer ack format against a live `fa03` capture — determine if
   it's the same characteristic with a different reply shape per command family,
   and whether `protocol/response.py` needs a second parser or a more general one.
7. Resolve the swipe-delete-without-disable question empirically (see above).

## File index (for direct navigation, no re-searching needed)

```
ble/BleProtocolN.java                     — dead setAlarmClock()/setTimeIndicator() stubs (lines 20-24)
bean/AlarmClock.java                      — dead data class, confirmed unused
core/data/TimerAgreement.java             — Timer feature: sendData / sendCloseData / ack parsing
core/db/bean/Timer.java                   — Timer field definitions
core/data/ScheduleAgreement.java          — Schedule feature: masterSwitch / gifSolve / imageSolve2 / textSolve / ack parsing
core/db/bean/Schedule.java                — Schedule top-level fields (master enable/buzzer)
core/db/bean/ScheduleTheme.java           — per-theme fields (week/time window/content)
ui/timer/AddTimerDialog.java              — Timer UI: content-type mapping (line ~655-671), duration labels (572-583), buzzer switch (314-327)
ui/timer/TimerActivity.java               — Timer UI: enable/disable toggle -> sendData vs sendCloseData (190-219), swipe delete (85-98, local-only)
util/ByteUtils.java                       — APP-LOCAL bit packer (getByteByArray/bitToByte) used by Schedule.masterSwitch — NOT the same class as below
../../tiro/jlotalibrary/util/ByteUtils.java — shared LE/BE helpers (short2Bytes=BE, int2byte=LE) — confirmed to match our protocol/bytes_.py
../../tiro/jlotalibrary/util/CrcUtils.java   — CRC32.CRC32() = standard java.util.zip.CRC32, confirmed equivalent to binascii.crc32
res/values/strings.xml                    — UI label ground truth (add_timer, alarm_clock_tips, duration labels)
```
