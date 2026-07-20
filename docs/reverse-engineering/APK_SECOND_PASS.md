*Migrated from the GlanceOS research lab, 2026-07-20. Historical evidence document — paths referenced inside may describe the original lab layout.*

# APK Second-Pass Findings (targeted, hardware-contradiction-driven)

Second pass over `C:\Users\Madhat\Documents\com.tech.idotmatrix.apk_Decompiler.com`,
scoped to the five questions raised by 2026-07-12 hardware testing that
contradicted or exceeded `APK_PROTOCOL_FINDINGS.md` / `ALARM_BUZZER_APK_FINDINGS.md`.
Those docs are **not edited** — corrections are called out explicitly below.

Labels: **CONFIRMED-FROM-SOURCE** (read directly, unambiguous) / **INFERRED**
(derived by hand-tracing logic, not copy-pasted) / **UNRESOLVED** (decompile
doesn't settle it).

---

## Q1 — ByteUtils byte order, both classes

**CONFIRMED-FROM-SOURCE.** Both classes define byte-identical `short2Bytes`/`int2byte`:

`com/tiro/jlotalibrary/util/ByteUtils.java:57-63`:
```java
public static byte[] short2Bytes(short s) {
    return new byte[]{(byte) ((s >> 8) & 255), (byte) (s & 255)};   // [hi, lo]
}
public static byte[] int2byte(int i) {
    return new byte[]{(byte) (i & 255), (byte) ((i >> 8) & 255), (byte) ((i >> 16) & 255), (byte) (i >>> 24)};  // [b0..b3] = LE
}
```
`com/tech/idotmatrix/util/ByteUtils.java:23-29` — identical bodies, byte-for-byte.

In isolation `short2Bytes` produces a **big-endian array** `[hi, lo]`. This is
exactly what the first pass read and reported as "BE". **That conclusion was
correct about the function in isolation but wrong about the wire**, because
every call site that uses `short2Bytes` for a header field **swaps the two
returned bytes when copying them into the packet**:

`TimerAgreement.java:129-131` (packet-length field, offset 0-1):
```java
byte[] bArrShort2Bytes = ByteUtils.short2Bytes((short) length);
bArr3[b] = bArrShort2Bytes[1];   // bArr3[0] = LOW byte
bArr3[1] = bArrShort2Bytes[b];   // bArr3[1] = HIGH byte  (b == 0)
```
Net result on the wire: **little-endian**. Same pattern at the duration field,
`TimerAgreement.java:142-143`: `bArr3[8]=bArrShort2Bytes2[1]; bArr3[9]=bArrShort2Bytes2[0];`
→ LE. `ScheduleAgreement.java:244-245` (Kotlin, all three header builders
`gifSolve`/`imageSolve2`/`textSolve`) does the identical swap for the
packet-length field.

The `int2byte` fields (payload length, CRC32) are written **without any swap**
— `TimerAgreement.java:155-162`, `ScheduleAgreement.java:256-263` — which is
consistent because `int2byte` already returns LE order (`b0..b3` low-to-high).

**Conclusion: every multi-byte header field in both TimerAgreement and
ScheduleAgreement lands on the wire in little-endian**, regardless of which
helper function built the intermediate array. This matches the 2026-07-12
hardware finding exactly ("ALL-little-endian... worked; the doc's BE claim
produced silence").

**Corrects** `ALARM_BUZZER_APK_FINDINGS.md` lines 56 and 94 ("packet length...
big-endian short", "duration... big-endian short") — both are wrong as stated;
the *function* is BE, the *wire bytes* are LE because of the swap at the call
site. The first pass's error was reading `short2Bytes`'s definition and
assuming a direct array copy, without tracing the individual `bArr[i] = ...`
assignments at each call site.

**Full field-by-field table, true wire byte order** (both TimerAgreement's
24-byte header and ScheduleAgreement's 23-byte header):

| Field | Helper used | Wire order |
|---|---|---|
| Packet length (offset 0-1) | `short2Bytes`, swapped at call site | **LE** |
| Timer duration (offset 8-9) | `short2Bytes`, swapped at call site | **LE** |
| Payload total length (int) | `int2byte`, direct copy | **LE** (function's native order) |
| CRC32 (int) | `int2byte`, direct copy | **LE** (function's native order) |
| Text char-count (`sendData`/`sendData832`/`textSolve` offset 0-1) | `short2Bytes`, swapped at call site | **LE** |

No field in either agreement class is actually BE on the wire — the first
pass's "BE" claims should all be re-read as LE, as the hardware found.

---

## Q2 — Timer/Schedule "image" content format

**CONFIRMED-FROM-SOURCE — Timer's IMAGE path is raw, uncompressed RGB, no header.**

`ui/timer/AddTimerDialog.java:718` (image load callback, `curMaterialType==0`):
```java
addTimerDialog.curMaterialData = BGRUtils.bitmap2RGB(addTimerDialog.curBitmap);
```
`util/BGRUtils.java:41-61`:
```java
public static byte[] bitmap2RGB(Bitmap bitmap) {
    int width = bitmap.getWidth(); int height = bitmap.getHeight();
    int[] iArr = new int[width*height];
    bitmap.getPixels(iArr, 0, width, 0, 0, width, height);
    byte[] bArr = new byte[width*height*3];
    // per pixel: bArr[i]=R, bArr[i+1]=G, bArr[i+2]=B, i+=3
    ...
}
```
This is **exactly** the raw-RGB-frame format the hardware test used (content-
type byte 2). The APK's own image path produces byte-identical framing:
`width*height*3` bytes, row-major, `[R,G,B]` per pixel, **no dimension header,
no compression, no frame markers**. Sent via `sendData(..., 2, ...)` at
`AddTimerDialog.java:657` (i==0 → protocol byte 2, matching the previously
documented content-type table).

`ui/timer/AddTimerDialog.java:746-748` (the `else` branch, i.e. `curMaterialType==1`,
GIF): `curMaterialData = FileIOUtils.readFile2BytesByStream(str)` — the **raw
bytes of the actual .gif file on disk**, unmodified, sent via `sendData(...,1,...)`.
This confirms why the hardware's real GIF bytestream (content-type 1) rendered:
it's genuinely just the GIF file's bytes, whatever the device's GIF decoder
supports (multi-frame animation included).

**Implication for the driver**: since our raw-RGB bytes are already
byte-identical to what the app itself sends for content-type 2, the fact that
hardware *saved but did not render* the image alarm content is **not a format
bug on our side** — the app's own format for "image" alarms is exactly what we
sent. This is either a firmware limitation specific to static-image timer/alarm
content (device may only render GIF-typed alarm content despite accepting and
storing image-typed content), or a dimension/size mismatch (raw RGB carries no
width/height — the device must infer size from total payload length against
its known panel dimensions; if our test payload's byte count didn't exactly
equal `panel_w * panel_h * 3` the device may silently fall back to the clock).
**UNRESOLVED**: whether content-type 2 timers ever render on real firmware —
recommend testing with a payload whose length is exactly `W*H*3` for the
connected panel's reported dimensions, since `BGRUtils.bitmap2RGB` always
sizes from the *decoded bitmap's own* width/height, which the app implicitly
trusts matches the panel.

**Schedule's IMAGE path is different from Timer's — genuine, confirmed asymmetry:**

`ui/schedule/NewScheduleThemeDialog.java:400`:
```java
NewScheduleThemeDialog.this.curMaterialData = BGRUtils.bitmapByte(NewScheduleThemeDialog.this.curBitmap);
```
`util/BGRUtils.java:35-39`:
```java
public static byte[] bitmapByte(Bitmap bitmap) {
    ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
    bitmap.compress(Bitmap.CompressFormat.PNG, 100, byteArrayOutputStream);
    return byteArrayOutputStream.toByteArray();
}
```
Schedule's per-theme IMAGE content (`imageSolve2`, protocol byte 10 = 2) is a
**single-frame PNG** (lossless, quality 100), not raw RGB. Also confirmed at
the theme-name-preset path, `ui/schedule/ScheduleThemeListActivity.java:601`
(`scheduleTheme.setImgData(BGRUtils.bitmapByte(...))`) — same call. Schedule's
GIF path (`gifSolve`, byte 10 = 1) uses the same raw-file-bytes approach as
Timer (`NewScheduleThemeDialog.java:434-436`).

**This is a real, source-confirmed difference between the two features** —
Timer IMAGE = raw RGB, Schedule IMAGE = PNG. Worth noting for the driver:
Schedule's `CONTENT_IMAGE` should almost certainly be sent as PNG bytes, not
raw RGB, if it's ever ported (currently out of scope per the existing docs,
but flagging since Q2 was specifically about content-type IMAGE format).

---

## Q3 — Week bitmask day mapping

**CONFIRMED-FROM-SOURCE.** Both UIs use `WeekVO(day, selected)` lists seeded
identically: `AddTimerDialog.java:354-361` and
`ScheduleThemeDialog: NewScheduleThemeDialog.java:636-643`:
```java
weekVOList.add(new WeekVO(1,false)); // index0
weekVOList.add(new WeekVO(2,false)); // index1
weekVOList.add(new WeekVO(3,false)); // index2
weekVOList.add(new WeekVO(4,false)); // index3
weekVOList.add(new WeekVO(5,false)); // index4
weekVOList.add(new WeekVO(6,false)); // index5
weekVOList.add(new WeekVO(7,false)); // index6
weekVOList.add(new WeekVO(0,true));  // index7 — "not repeating" UI toggle only
```
`common/WeekConvert.java:9-26` confirms `day`: 1=Mon, 2=Tue, 3=Wed, 4=Thu,
5=Fri, 6=Sat, 7=Sun, 0="not_repeating" (string only, not a real day).

**Timer's raw byte** (`AddTimerDialog.java:424-433`, `saveData()`):
```java
byte[] bArr = new byte[8];
bArr[0] = 1;                                  // constant
for (i=0..6) bArr[i+1] = weekVOList.get(i).isSelected() ? 1 : 0;   // index7 excluded
byte week = ByteUtils.getByteByArray(bArr);
```
`getByteByArray`/`bitToByte` (`ByteUtils.java:111-137`, both classes,
byte-identical) read the input array **back-to-front** into a string, then
parse that string as binary **MSB-first** — i.e. `bArr[7]` becomes bit7 (MSB),
`bArr[0]` becomes bit0 (LSB). Traced by hand:

| Timer raw week byte, bit | Source | Meaning |
|---|---|---|
| bit0 (LSB) | `bArr[0]` (constant 1 in `saveData`, or preserved from existing value on edit — see `AddTimerDialog.java:473,495-499`, drives `timer.setEnabled(...)`) | **timer-enabled flag, not a day** |
| bit1 | `weekVOList[0]` | Monday |
| bit2 | `weekVOList[1]` | Tuesday |
| bit3 | `weekVOList[2]` | Wednesday |
| bit4 | `weekVOList[3]` | Thursday |
| bit5 | `weekVOList[4]` | Friday |
| bit6 | `weekVOList[5]` | Saturday |
| bit7 (MSB) | `weekVOList[6]` | Sunday |

`weekVOList[7]` (the "not repeating" toggle) is **never included** in Timer's
byte at all — confirmed by the loop bound `i < weekVOList.size()-1`.
**Timer never calls `patch()`** — confirmed by exhaustive grep of
`TimerAgreement.java` for the string "patch": zero matches.

**Schedule's raw byte** — `ble/BleProtocol.java:18-31`, `convertWeekByte()`:
```java
byte[] bArr = new byte[8];
for (i=0..7) bArr[i] = weekVOList.get(i).isSelected() ? 1 : 0;   // ALL 8 entries, incl. index7
return ByteUtils.getByteByArray(bArr);
```
Same reversal/MSB-first packing, but this time **all 8** `weekVOList` slots
are packed (including index7, the "not repeating" toggle):

| Schedule raw week byte, bit | Source | Meaning |
|---|---|---|
| bit0 (LSB) | `weekVOList[0]` | Monday |
| bit1 | `weekVOList[1]` | Tuesday |
| bit2 | `weekVOList[2]` | Wednesday |
| bit3 | `weekVOList[3]` | Thursday |
| bit4 | `weekVOList[4]` | Friday |
| bit5 | `weekVOList[5]` | Saturday |
| bit6 | `weekVOList[6]` | Sunday |
| bit7 (MSB) | `weekVOList[7]` | "not repeating" UI flag |

This is a **different raw bit layout from Timer's** — Schedule's storage
format is day-index-ordered starting at bit0=Monday with the "no day picked"
flag at bit7, whereas Timer's storage format already has the enabled-flag at
bit0 and days starting at bit1.

**`patch()`, character by character** (`ScheduleAgreement.java:218-227`):
```kotlin
private final int patch(int number) {
    if (number < 0) number += 255                      // (1) unsign the byte-as-int
    val binaryString = Integer.toBinaryString(number)   // (2) shortest binary repr, no leading zeros
    val str = String.format("%8s", binaryString)         // (3) left-pad with SPACES to width 8
        .replace(' ', '0')                                // (4) spaces -> '0' (zero-pad)
    return Integer.parseInt(str.removeRange(0,0) + "1", 2) // (5) drop char[0] (MSB), append "1" as new LSB
}
```
Step (5) removes the **original MSB (bit7)** and appends a constant `1` as
the **new LSB (bit0)**, shifting every other original bit down one position.
In terms of the original bits `[b7 b6 b5 b4 b3 b2 b1 b0]`:

```
patched = [ b6 b5 b4 b3 b2 b1 b0 1 ]     (b7 discarded, new bit0 forced to 1)
```

Applying this to Schedule's raw layout (`b0`=Mon … `b6`=Sun, `b7`=not-repeating):

| Post-patch bit | = original | Meaning |
|---|---|---|
| bit0 (new, forced) | constant `1` | enabled/active flag |
| bit1 | `b0` | Monday |
| bit2 | `b1` | Tuesday |
| bit3 | `b2` | Wednesday |
| bit4 | `b3` | Thursday |
| bit5 | `b4` | Friday |
| bit6 | `b5` | Saturday |
| bit7 | `b6` | Sunday |

**This is now bit-for-bit identical to Timer's raw (already-wire-format) week
byte.** `patch()` exists specifically to convert Schedule's UI-storage bit
order into the same wire format Timer's UI already produces natively —
confirming why Timer skips `patch()`: it never needed it. The "not repeating"
flag (original `b7`) is **discarded entirely** by `patch()`, replaced by the
constant enabled-bit.

**INFERRED, side note (possible app bug, not one of the hardware
contradictions but discovered while tracing this character-by-character)**:
step (1) uses `number += 255`, but converting a sign-extended negative byte
back to its unsigned 0-255 value requires **+256**, not +255. `getWeek()`
returns `int` (`core/db/bean/ScheduleTheme.java:85`) populated from a `byte`
via implicit widening, so it sign-extends when bit7 is set — which happens
precisely when the user picks **no specific day** (the default/"not
repeating" case, `weekVOList[7]` true, byte = `0x80` = `-128` as a signed int).
Hand-tracing `patch(-128)`: `-128+255=127` → `"1111111"` (7 bits, no leading
zero character was emitted by `toBinaryString`) → padded to `"01111111"` →
drop first char → `"1111111"` → append `"1"` → `"11111111"` = **0xFF (every
day flagged)**. The mathematically-intended value (`+256` instead of `+255`)
would have produced `0x01` (no days flagged, enabled-bit only). Whether this
is by design (defaulting "no day picked" to "every day") or an off-by-one bug
is **UNRESOLVED** without a live capture — flagging since it directly affects
what a Schedule theme with no explicit day selection actually fires on.

---

## Q4 — Ack correlation in the app

**CONFIRMED-FROM-SOURCE — there is no content-based routing at the transport
layer; every registered listener sees every frame, and a "current command"
single-slot callback also sees every frame unconditionally.**

`com/heaton/baselib/ble/BleManager.java:488-501`, the single central notify
handler for the whole app (triggered once per BLE notification, all features
funnel through here):
```java
public /* synthetic */ void lambda$onChanged$0(BluetoothGattCharacteristic c, BleDevice bleDevice) {
    if (c.getService().getUuid().equals(BleManager.UUID_SERVICE)) {
        byte[] value = c.getValue();
        if (BleManager.this.sendResultCallback != null) {
            BleManager.this.sendResultCallback.onResult(bleDevice, value);   // (A) single global slot, NO filtering
        }
        for (BleListener bleListener : BleManager.this.bleListeners) {
            bleListener.onChanged(bleDevice, value);                         // (B) broadcast to every registered listener
        }
    }
}
```
Two independent, unfiltered mechanisms:

**(A) Single-slot `sendResultCallback`** — `BleManager.java:584-592`,
`writeAll(byte[], SendResultCallback)`:
```java
public boolean writeAll(byte[] bArr, SendResultCallback sendResultCallback) {
    ...
    this.sendResultCallback = sendResultCallback;   // overwrites whatever was there
    write(connetedDevices.get(0), bArr);
    return true;
}
```
This is a **single mutable field**, not a queue or a map keyed by command.
Whichever `writeAll(bytes, callback)` call happens most recently owns the slot
until the *next* such call overwrites it. `verifyPwd` (`BleProtocolN.java:161-173`)
and `SendCore.sendDiyImageData` (the app's real-time DIY/graffiti-paint sender,
`ble/send/SendCore.java:240-262`, which calls `sendCompat(payload, callback)` →
ultimately `writeAll(bytes, callback)`) **both go through this exact same
single slot**. There is **no byte-content check by BleManager itself** — the
raw notify frame is handed to whatever `SendResultCallback` is currently
installed, full stop; any filtering has to happen inside that callback's own
implementation.

**(B) Persistent `BleListener` broadcast list** — every listener registered
via `bleManager.registerBleListener(...)` (TimerAgreement, ScheduleAgreement,
MutilColorAgreement, etc., each in their own constructor) receives **every**
notify frame for as long as it stays registered, and does its own prefix
matching, e.g. `ScheduleAgreement.verifyMasterSwitch` (`ScheduleAgreement.java:609-617`,
checks `data[0]==5 && data[1]==0 && data[2]==7 && data[3]==-128`) vs.
`verifySetup` (`:620-628`, checks `data[2]==5` instead of `7`) — these two are
distinguished only by manually inspecting 4 leading bytes inline, with no
shared abstraction and no cross-listener awareness that a frame might also
match a *different* listener's prefix.

**Direct answer — could the app confuse a graffiti nack with a verifyPwd
reply?** Yes, plausibly, via mechanism (A): `verifyPwd` sends
`[7,0,5,2,b1,b2,b3]` (`BleProtocolN.java:161-173`) and — per the standard ack
convention this whole protocol family uses (`[cmd_len_byte,0,type,subtype,status]`)
— its expected reply shape would be `[5,0,5,2,status]`. The 2026-07-12
hardware test observed graffiti's rejection nack as **exactly**
`[5,0,5,2,0]` — the identical 4-byte prefix. If `verifyPwd`'s
`SendResultCallback.onResult` implementation (not visible in this decompile;
`verifyPwd` passes the caller's callback through opaquely) does not itself
re-validate the frame content and simply trusts "a callback fired, read
byte[4]", then any write that shares the single `sendResultCallback` slot —
including a graffiti/DIY-paint send via `SendCore.sendDiyImageData` — sent
close in time to a pending `verifyPwd` would have its reply silently
delivered to the wrong caller. **UNRESOLVED** whether the real app ever
triggers this in practice (it likely avoids it by construction — the
password-entry UI and the DIY-paint canvas are never open simultaneously —
but the *mechanism* has no interlock preventing it if it ever were).

**Design implication for our driver**: the app's own correlation model is
strictly weaker than what our driver already does (keying acks by
(type,subtype)) — it is a "trust the last writer" single slot plus an
unfiltered broadcast list, relying entirely on the app's UI-level discipline
(never issue two commands whose replies could look similar) rather than any
protocol-level correlation. Our driver should **not** try to imitate this
model; if anything this confirms the value of serializing outstanding
commands and/or timing out stale ones, since even the vendor app has no
better guarantee than "don't race yourself."

---

## Q5 — Quick opportunistic reads

**(a) `MutilColorAgreement.java` — effect speed and chunked color-list format.**
CONFIRMED-FROM-SOURCE. `sendMutilColor()` (`MutilColorAgreement.java:42-72`):
header `[len, 0, 3, 2, modelIndex, speed, colorCount]` (7 bytes) followed by
`colorCount * 3` bytes of RGB triples, **each channel individually passed
through `ColorConverter.calculationByColour(component, saturation)`** (a
saturation-adjustment function, not raw RGB) — `bArr[5] = (byte) lightsColor.getSpeed()`
is a real, distinct field (byte offset 5), separate from saturation (applied
per-channel to the color list, not a header byte). This flat header+list is
then re-packetized for BLE transport by `getSendData()` (`:84-119`) into
device-MTU-sized chunks (96 bytes if MTU negotiated, else 18), each chunk
prefixed with its own 2-byte `[chunkLen+1, chunkIndex]` sub-header — a
**different, bespoke chunking scheme** from the 4096/509-byte scheme
Timer/Schedule/GIF/Image use.

**(b) `SendCore.changeLight` — pixel dimming formula.** CONFIRMED-FROM-SOURCE.
`SendCore.java:146-151`:
```kotlin
private fun changeLight(bright: Int, data: ByteArray) {
    for (i in data.indices) data[i] = (((data[i] & 0xFF) * bright) / 100).toByte()
}
```
Simple linear per-byte scale: `newByte = (byte & 0xFF) * bright / 100`, integer
division, `bright` is a 0-100 percent value. Applied in-place to every byte of
the frame payload (not per-channel-aware — it multiplies raw pixel bytes
uniformly, which is correct for RGB frames since R/G/B are dimmed identically).
Called from `payload()` only `if (bright != 100)` (`SendCore.java:105-107`).

**(c) Graffiti command's byte 3, app's own sender.** CONFIRMED-FROM-SOURCE,
and this resolves a structural mismatch: **the APK's own `SendCore.sendDiyImageData`
(the app's real-time paint-stroke sender, previously hypothesized in pass 1 to
be a related-but-distinct feature) never varies byte 3 — it is a hardcoded
constant `1`**, part of `getDataType(5) = {5, 1}` (`SendCore.java:139-140`),
written directly into the packet at `SendCore.java:96` (`bArr[3] = dataType[1]`).
The app's actual variable "option" byte for this command is **byte 4**
(`bArr[4] = (byte) option`, `SendCore.java:97`, where `option = item.getMoveType()`,
the `DiyImageMoveType` enum 0-4 documented in pass 1). This means **our
`protocol/graffiti.py`'s byte-3 "mirror 1-4" field has no counterpart at all
in the app's own DIY/paint protocol** — the app's byte 3 is pinned at 1 and
its real option/mirror-equivalent field lives one byte later, at offset 4.
Since our graffiti command is structurally a different, "flatter" wire format
than `SendCore`'s envelope (confirmed again here: header lengths differ — our
8-byte header vs. `SendCore`'s 5-byte header for type 5 — and field order
differs — we put RGB right after byte 4, `SendCore` puts RGB as the start of
`data` after a 5-byte header with the option byte already consumed), **no
named constant for our byte 3 exists anywhere in this decompile** — it isn't
part of any code path the app itself sends. The hardware result (0/1/2/4
identical, 3 rejected) can't be cross-checked against real app traffic for
that exact field; it's likely an artifact of how the *device firmware*
happens to interpret an unused/legacy byte in an older command variant that
the current app no longer sends this way. **UNRESOLVED** — recommend treating
our byte-3 field as effectively an undocumented device-firmware quirk rather
than something the current app's source can validate further.
