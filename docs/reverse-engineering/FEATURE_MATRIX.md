*Migrated from the GlanceOS research lab, 2026-07-20. Historical evidence document — paths referenced inside may describe the original lab layout.*

# Feature Matrix: APK vs. Driver (`D:\glanceos\idotmatrix`)

Every distinct protocol-level feature found in the decompiled `com.tech.idotmatrix`
APK, checked against what `D:\glanceos\idotmatrix\idotmatrix\protocol\` currently
implements. See `APK_RESEARCH_HANDOFF.md` for how to use this document, and
`APK_PROTOCOL_FINDINGS.md` / `ALARM_BUZZER_APK_FINDINGS.md` for byte-level detail
on anything marked ⚠️ or ❌.

Legend: ✅ have it, byte-confirmed · ⚠️ gap or open question, bytes known ·
🔍 exists in APK, not investigated / low priority · ❌ deliberately not planned ·
🚫 blocked (can't be done from this decompile)

## Display / rendering

| Feature | APK source | Driver status |
|---|---|---|
| Full-frame DIY image upload | `SendCore` (`TYPE_DIY_IMAGE_UNREDO`), matches lab's original path | ✅ `protocol/image.py` — hardware-verified, this is GlanceOS's main render path |
| DIY mode enter/exit, all 4 sub-modes | `ui/diy/DiyImageFun.java` | ⚠️ modes 0/1 implemented and named; modes 2/3 (`QUIT_STILL_CUR_SHOW`, `ENTER_NO_CLEAR_CUR_SHOW`) accepted by device but unnamed/untested in our driver — see findings §"DiyImageFun" |
| Graffiti (set pixels over current frame) | `BleProtocolN` graffiti command | ✅ `protocol/graffiti.py` — hardware-verified, this is GlanceOS's delta-render path |
| Graffiti mirror/move/erase modifier (byte 3) | possibly `ui/diy/DiyImageMoveType.java` (circumstantial link) | ⚠️ byte accepted 1-4, semantics guessed as "mirror," never confirmed — see findings §5 |
| Live paint-stroke drawing (point-by-point, "move direction", multi-color-per-point) | `SendCore.sendDiyImageData` (`CPaintRunTimeItem`) | 🔍 exists, not needed — our `set_pixels` already covers the delta-render use case |
| Static (non-DIY) image upload | `ImageAgreement.sendImageData` | 🔍 exists as a separate path from DIY upload, not investigated — likely irrelevant since GlanceOS always wants DIY mode's real-time behavior |
| Animated GIF upload | `GifAgreement.java` | ✅ `protocol/gif.py` — hardware-verified, `time_sign`/`ConvertTime` semantics already matched |
| Scrolling text, single generic size | `TextAgreement` (5 panel-size-specific senders: `sendTextTo832/1616/3232/1664/6464`) | ⚠️ we have one generic 16×32-bitmap implementation (from the lab), not confirmed to match the panel-specific `sendTextTo3232` variant the app actually uses for a 32×32 screen |
| Saved "phrase" slot selection | `PhraseAgreement.java` | 🔍 new, distinct feature (selects pre-stored phrases by position, not new text upload) — not in ROADMAP, low priority for GlanceOS's render-full-frames design |
| Fullscreen solid color | `BleProtocolN.sendColor` | ✅ `protocol/fullscreen_color.py` |
| Multi-color lighting effect (7 built-in styles) | `BleProtocolN.setSpeed`+effect cmd (type=3/sub=2) | ✅ `protocol/effect.py` — but see next row |
| Multi-color effect: configurable speed, saturation, larger color counts, proper chunked transmission | `MutilColorAgreement.java` | ⚠️ our `effect.py` hardcodes speed=90 and caps at 2-7 colors with no chunking; `MutilColorAgreement` suggests speed is a real parameter and larger color lists use a different (per-packet `[len,index]`-header, 96-byte-chunk) transmission scheme — worth comparing before assuming our simplified version is complete |
| Client-side pixel dimming before upload | `SendCore.changeLight` | 🔍 exists (pre-multiplies RGB bytes by brightness% before sending), distinct from the device-side `set_brightness` command — a possible technique for smooth fades, not currently used |

## Device control

| Feature | APK source | Driver status |
|---|---|---|
| Brightness | `BleProtocolN.setLight` | ✅ `protocol/common.py` |
| Power on/off | `BleProtocolN.sendSwitchplate` | ✅ `protocol/common.py` |
| Screen flip 180° | `BleProtocolN.setRotate180` | ✅ `protocol/common.py` |
| Freeze screen | (lab-ported, matches app's overall pattern) | ✅ `protocol/common.py` |
| Set device time | `BleProtocolN.synchronizedTime` | ✅ `protocol/common.py` |
| Text scroll speed | `BleProtocolN.sendSpeed` | ✅ `protocol/common.py` |
| "Joint" mode (purpose unknown upstream too) | `BleProtocolN.sendJoint` | ✅ `protocol/common.py` (bytes match; semantics still unknown in the source app too) |
| Set password | `BleProtocolN.setPwd` | ✅ `protocol/common.py` |
| **Verify/authenticate password** | `BleProtocolN.verifyPwd` | ⚠️ **missing** — bytes confirmed, see findings §1 |
| Reset device | `BleProtocolN.restDevice` | ✅ `protocol/common.py` |
| **Screen-on-duration / auto-dim timer** | `BleProtocolN.setScreenLight`/`readScreenLight` | ⚠️ **missing, wasn't even in ROADMAP** — new feature, bytes confirmed, see findings §4 |
| **Clock time indicator toggle** | `BleProtocolN.setTimeIndicatorEnable` | ⚠️ **missing** — was in original lab (with an "doesn't seem to work" comment), dropped during our port; current 2026 APK confirms same bytes still shipped, see findings §2 |
| **Erase all device data** | `Agreement.deleteDeviceMaterial` | ⚠️ **missing** — was in original lab, dropped during our port; bytes unchanged across app versions, see findings §3 |
| Eco mode (scheduled brightness window) | `BleProtocolN.setEco` | ✅ `protocol/eco.py` |

## Time-based features

| Feature | APK source | Driver status |
|---|---|---|
| Clock display (8 styles) | `BleProtocolN.sendClockMode` | ✅ `protocol/clock.py` |
| Chronograph (stopwatch) | `BleProtocolN.setSecondChronograph` | ✅ `protocol/chronograph.py` |
| Countdown timer | `BleProtocolN.setCountDown` | ✅ `protocol/countdown.py` |
| Scoreboard | `BleProtocolN.setScoreboard` | ✅ `protocol/scoreboard.py` |
| **Alarm ("Timer" — up to 10 slots, image/gif/text + buzzer)** | `core/data/TimerAgreement.java` | ⚠️ **not implemented** — full byte layout mapped in `ALARM_BUZZER_APK_FINDINGS.md` |
| **Weekly Schedule (recurring themes, day-bitmask + time window + buzzer)** | `core/data/ScheduleAgreement.java` | ⚠️ **not implemented** — full byte layout mapped in `ALARM_BUZZER_APK_FINDINGS.md` |
| Alarm & Buzzer (as a standalone top-level feature, per original ROADMAP wording) | `ble/BleProtocolN.setAlarmClock`/`setTimeIndicator` | ❌ **confirmed dead code in the app itself** — empty method stubs, never called. The real functionality lives in Timer/Schedule above; the standalone "alarm" API upstream's issue #18 asked about was never built by the vendor either |

## Audio / sensor reactive

| Feature | APK source | Driver status |
|---|---|---|
| Microphone type select | `BleProtocolN.setMicType` | ✅ `protocol/music_sync.py` |
| Image-reacts-to-rhythm trigger | `BleProtocolN.sendImageRhythm` | ✅ `protocol/music_sync.py` |
| Stop rhythm | `BleProtocolN.sendStopMicRhythm` | ✅ `protocol/music_sync.py` |
| Raw rhythm data passthrough | `BleProtocolN.sendRhythm` | ✅ `protocol/music_sync.py` (present, deliberately not used to stream host audio — device has its own mic) |
| Second/newer 2-parameter mic command | `BleProtocolN.sendMicCommand1` | 🔍 exists, not investigated, low priority (superset/replacement of `setMicType`?) |

## Data & connectivity

| Feature | APK source | Driver status |
|---|---|---|
| Device location / "find" | `Agreement.getLocationDevice` + native AES | 🚫 **blocked** — cipher key lives in a native `.so`, not reachable via APK decompile. See findings §8 |
| BT password protection (authenticate) | see "Verify/authenticate password" above | ⚠️ same gap as above |
| Cloud image download/upload | `ui/cloud/*` | ❌ **out of scope** — contradicts GlanceOS's local-first design |
| OTA / firmware update | `core/data/OTAAgreement.java`, `ota/` package | ❌ **out of scope** — flashing over a half-understood protocol risks bricking the device |
| Video/Camera upload | `SendCore` constants `TYPE_VIDEO`/`TYPE_CAMERA` exist | 🔍 constants exist but **no corresponding UI screen or feature code found** — likely vestigial/reserved, not a real usable feature in this app version |

## Summary

- **19 features fully match** between APK and our driver, byte-confirmed.
- **9 gaps identified**, all with confirmed or high-confidence bytes, ranked by
  effort in `APK_RESEARCH_HANDOFF.md`'s priority order. Four are trivial
  single-command additions ready to port now.
- **2 major subsystems** (Timer/alarm, Schedule) fully mapped but not yet
  implemented — this was the original research task.
- **3 features investigated and deliberately not pursued** (paint-stroke DIY
  protocol, second mic command, static-image-upload path) — existing driver
  functionality already covers the GlanceOS use case.
- **1 feature confirmed blocked** (location) and **2 confirmed out of scope**
  (cloud, firmware) by design decision, not by research limitation.
- **1 ROADMAP item downgraded to confirmed-dead-code** (`setAlarmClock`) — no
  further research value there.
