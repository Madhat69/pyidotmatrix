*Migrated from the GlanceOS research lab, 2026-07-20. Historical evidence document — paths referenced inside may describe the original lab layout.*

# Additional APK Findings for the Desktop Driver

Second pass over the decompiled `com.tech.idotmatrix` APK (same source as
`ALARM_BUZZER_APK_FINDINGS.md`), this time scanning for anything relevant to
existing driver gaps rather than alarm/buzzer specifically. Cross-referenced
against `D:\glanceos\idotmatrix\idotmatrix\protocol\` to confirm what's actually
missing vs. already ported.

Confidence levels used below: **confirmed** (byte-identical to already-verified
code, or a trivial single command with an obvious ack path) / **hypothesis**
(strong circumstantial evidence, needs a hardware test to confirm) / **blocked**
(cannot be resolved from this decompile at all).

## Ready to port now (small, safe, high confidence)

### 1. `verify_password` — closes a real ROADMAP gap, byte-confirmed

We have `build_set_password` (`protocol/common.py`) but nothing to *authenticate*
against an already-locked device. `BleProtocolN.java:161-173`:

```java
public static void verifyPwd(String str, SendResultCallback sendResultCallback) {
    // str.substring(0,2), (2,4), (4,6) parsed as decimal bytes
    BleManager.getInstance().writeAll(new byte[]{7, 0, 5, 2, b1, b2, b3}, sendResultCallback);
}
```
Same 6-digit-as-3-bytes encoding our `build_set_password` already uses (verified:
`setPwd` at line 150-159 uses the identical split, confirming our existing
`(password // 10000) % 256` etc. math is correct). Add:
```python
def build_verify_password(password: int) -> bytearray:
    high, mid, low = (password // 10000) % 256, (password // 100) % 100 % 256, password % 100 % 256
    return bytearray([7, 0, 5, 2, high, mid, low])
```
Ack shape unconfirmed but likely fits the standard `[0x05,0x00,type,subtype,status]`
pattern our `protocol/response.py` already parses — verify on hardware with a
device that actually has a password set.

Note: `setPwd`'s byte 4 is a variable `i` (mode?), not hardcoded — our existing
`build_set_password` hardcodes it to `1`. Not investigated further; low risk since
our version is already lab/hardware-tested.

### 2. `set_time_indicator` — was in the lab, silently dropped in our port

The **original lab's** `clock.py` had this (with a "does not seem to work
currently" comment) and it did **not** make it into our new driver's
`protocol/clock.py`. `BleProtocolN.java:61-64` confirms the exact same bytes in
the current 2026 APK:
```java
public static void setTimeIndicatorEnable(boolean z) {
    byte[] bArr = {5, 0, 7, ByteCompanionObject.MIN_VALUE, z ? 1 : 0};  // [5,0,7,0x80,1|0]
}
```
Since the current official app still ships this exact command, it's real (the
lab's "doesn't work" comment is more likely a specific firmware/model quirk than
wrong bytes). Per your standing decision, add this **behind the same
experimental gating** as the other unverified clock features:
```python
def build_set_time_indicator(enabled: bool) -> bytearray:
    return bytearray([5, 0, 7, 128, 1 if enabled else 0])
```

### 3. `delete_device_data` ("erase device data") — confirmed stable across versions, currently absent

The lab's `system.py` had this; **it did not make it into our new driver at all**.
`core/data/Agreement.java:7-9` (2026 APK) has byte-identical bytes to the old
lab version:
```java
public static byte[] deleteDeviceMaterial() {
    return new byte[]{17, 0, 2, 1, 12, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};
}
```
Identical bytes across app versions is a good stability signal. This is exactly
your "device erase/reset-beyond-current-reset" ROADMAP item — add it **behind an
experimental/confirm-before-use gate** given what it does:
```python
def build_delete_device_data() -> bytearray:
    return bytearray([17, 0, 2, 1, 12, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
```

### 4. Screen-on-duration / auto-dim timer — genuinely new feature, not in ROADMAP at all

Not something we knew was missing because we didn't know it existed.
`BleProtocolN.java:47-55`:
```java
public static void setScreenLight(int i) {  // [5, 0, 15, 0x80, i]
public static void readScreenLight() {      // [5, 0, 15, 0x80, 0xFF]  -- 0xFF = "read" sentinel
```
Same shape as `set_brightness` (single 5-byte command, byte 4 = value, `0xFF` at
byte 4 requests a read-back). Chinese log string translates to "set screen-on
time" — likely an auto-sleep/dim timer, distinct from `eco` mode (which is a
scheduled brightness window) and distinct from `set_power`. Low risk to add:
```python
def build_set_screen_timeout(value: int) -> bytearray:
    return bytearray([5, 0, 15, 128, value])
def build_read_screen_timeout() -> bytearray:
    return bytearray([5, 0, 15, 128, 0xFF])
```
Needs a hardware test to learn the units (seconds? minutes? an enum of presets?)
and to confirm the read variant actually returns something over fa03.

## Needs hardware verification before touching existing code

### 5. Graffiti "mirror" byte may actually be a 5-way option, not a 4-way mirror

Our `protocol/graffiti.py` treats header byte 3 as "mirror 1-4" (a guess from the
original lab author's comment, never verified). The 2026 APK has a *related but
distinct* enum, `ui/diy/DiyImageMoveType.java`:

| value | name |
|---|---|
| 0 | NO_EFFECT |
| 1 | HORIZONTAL_MIRROR |
| 2 | VERTICAL_MIRROR |
| 3 | OVERALL_MOVEMENT |
| 4 | ERASE |

This is used by `SendCore.sendDiyImageData()` — the app's live paint-stroke
protocol (see finding #6 below), at a **different byte offset** (header offset 4,
"option") than our graffiti command's offset-3 mirror byte, and via a **different
top-level command type** (`TYPE_DIY_IMAGE=5`/subtype=1, sent through the generic
`SendCore.payload()` envelope) than our graffiti command (also type=5, but a
flatter, older-looking wire format with no generic envelope). **These are likely
two different device features that happen to share the type=5 number by
coincidence**, not the same field — do not assume the numeric mapping transfers
directly.

That said, it's a strong hint about what our graffiti "mirror" byte *conceptually*
might be doing, since "mirror + move + erase" is a much more plausible option set
for a pixel-drawing tool than "four flavors of mirror." **Recommended test**: with
a small, asymmetric test pattern already on screen, send `mirror=0,1,2,3,4`
(currently out of range — `MAX_MIRROR=4` already permits testing 1-4, would need
to temporarily allow 0 too) via our *existing, working* `graffiti.set_pixels` and
watch what each value actually does. Do not change the shipped code until this is
confirmed — our current implementation is hardware-verified and works; this is
about learning what the untested values 2-4 do, matching the ROADMAP's existing
"graffiti mirror modes 2-4 unverified" item with better hypotheses to test against.

### 6. A second, newer DIY paint-stroke protocol exists (`SendCore.sendDiyImageData`)

Distinct from both our `image.py` (full-frame DIY upload) and our `graffiti.py`
(pixel-set command). `ble/send/SendCore.java:240-262` builds payloads for:
single-point-plus-fill (`color + column + row`), multi-point-same-color (`color +
[x,y,x,y,...]`), multi-point-different-colors (`diffColor + [x,y,...]`), or a
raw "move direction" array when `moveType == OVERALL_MOVEMENT`. This looks like
the app's live-drawing canvas tool sending incremental stroke updates as the user
draws, as opposed to our two existing paths (whole-frame push, or a flat
same-color pixel-set). **Not clearly better than what we have** — our
`DisplayBackend.set_pixels` already does same-color multi-point sets, which is
the delta-rendering primitive that matters for GlanceOS. This is presented as
context, not a recommended addition; flagging so nobody rediscovers it and
assumes it's unexplored.

### 7. A second, 2-parameter mic command exists (`sendMicCommand1`)

`BleProtocolN.java:183-185`:
```java
public static void sendMicCommand1(boolean z, int i, int i2) {
    BleManager.getInstance().writeAll(new byte[]{6, 0, 11, ByteCompanionObject.MIN_VALUE, (byte) (i + 1), (byte) i2}, null);
}
```
Different command-length byte (6, not 5) and an extra parameter vs. our existing
`set_mic_type` ([5,0,11,0x80,type]). The `boolean z` parameter isn't used in the
byte array at all (dead or vestigial in this decompile). Since MusicSync audio
streaming is explicitly out of scope for GlanceOS (device has its own mic), this
is low priority — noted for completeness, not recommended for porting.

## Confirmed blocked (do not spend more time here without a different approach)

### 8. `get_device_location` — the AES key is in a native library, not reachable from this decompile

`csh/tiro/cc/aes.java`:
```java
public class aes {
    public static native void cipher(byte[] bArr, byte[] bArr2);
    public static native void keyExpansionDefault();
    static { System.loadLibrary("AES"); }
}
```
Every method is `native` — the actual cipher and key material live in a compiled
`libAES.so`, invisible to Java/Kotlin decompilation. This **definitively confirms**
why the lab's `get_device_location` (which encrypts with a random per-call key)
can never work — there was never a way to get the real key from this level of
analysis. Fixing this for real would require either (a) disassembling the native
`.so` (ARM/x86 binary RE, a fundamentally different skill/tool than APK
decompilation), or (b) capturing real encrypted traffic from the official app
against a real device via a BLE sniffer and treating the cipher as an oracle. Both
are large, separate undertakings — recommend leaving this closed rather than
half-attempting it. `Agreement.java:11-13` confirms the plaintext command anyway
(`"LOCATE"` + padding), in case (b) is ever pursued.

## Confirmed matches (no action — listed so nobody re-verifies these)

`synchronizedTime`, `setEco`, `restDevice`, `setLight`, `setRotate180`,
`setCountDown`, `setSecondChronograph`, `setScoreboard`, `setMicType`,
`sendImageRhythm`, `sendStopMicRhythm`, `sendColor`, `sendSpeed`, `enterDiy`,
`sendClockMode`, `sendSwitchplate`, `sendJoint` all byte-match our existing
`protocol/*` builders exactly. `SendCore`'s `TYPE_DIY_IMAGE_UNREDO` (type=6,
maps to header bytes `{0,0}`, no CRC) independently confirms our existing
`image.py` DIY-frame header (type=0/subtype=0, no CRC field) is the right,
current-firmware-supported path — this is the "full frame" push GlanceOS uses.

## `DiyImageFun` — resolves the ROADMAP's "ImageMode 2 and 3 unknown" item

`ui/diy/DiyImageFun.java` — the enum backing `enterDiy(int)` / our
`build_set_diy_mode`:

| value | name |
|---|---|
| 0 | QUIT_NOSAVE_KEEP_PREV |
| 1 | ENTER_CLEAR_CUR_SHOW |
| 2 | QUIT_STILL_CUR_SHOW |
| 3 | ENTER_NO_CLEAR_CUR_SHOW |

Our current `image.py` only exposes 0/1 (`DIY_MODE_DISABLE`/`DIY_MODE_ENABLE`),
matching `QUIT_NOSAVE_KEEP_PREV`/`ENTER_CLEAR_CUR_SHOW`. **Safe, low-risk addition**:
expose all four named constants (just naming existing accepted values — the
device already accepts 0-3, we've just never had names for 2/3). Two of these
look specifically useful for GlanceOS:
- `ENTER_NO_CLEAR_CUR_SHOW` (3) — entering DIY mode *without* clearing the
  current display first. Could eliminate the black-flash-then-frame effect our
  `_ensure_diy_mode()` currently causes on first frame after connect.
- `QUIT_STILL_CUR_SHOW` (2) — leaving DIY mode while keeping the last frame
  visible, useful if a scene ever needs to temporarily hand the panel to a native
  mode (e.g. countdown) and return without a blank flash.

Both are hypotheses about *behavior*, not just names — the names are a direct,
confirmed read from the APK; what they *do* to the display still wants a quick
hardware check before GlanceOS's Presenter relies on them for flash-free
transitions.

## Suggested order

1. Port #1-4 (verify_password, set_time_indicator, delete_device_data,
   screen-timeout) — all confirmed bytes, all trivial single/flat commands, same
   pattern as everything already in `protocol/common.py`. Gate #2 and #3 as
   experimental per your existing decision.
2. Add the `DiyImageFun` named constants (2/2a above) — zero risk, just naming.
3. Hardware-test `ENTER_NO_CLEAR_CUR_SHOW` / `QUIT_STILL_CUR_SHOW` for the
   flash-free-transition hypothesis — directly useful for the Presenter.
4. Hardware-test graffiti mirror values 0-4 against the `DiyImageMoveType` labels.
5. Leave #6 (paint-stroke protocol), #7 (second mic command), and #8 (location)
   alone — correctly out of scope or genuinely blocked.
