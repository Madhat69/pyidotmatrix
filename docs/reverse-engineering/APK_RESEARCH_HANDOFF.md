*Migrated from the GlanceOS research lab, 2026-07-20. Historical evidence document — paths referenced inside may describe the original lab layout.*

# APK Research Handoff

Entry point for picking up the decompiled-APK research. Three documents, read in
this order:

1. **This file** — orientation, priority order, what's safe to touch.
2. **[FEATURE_MATRIX.md](FEATURE_MATRIX.md)** — every protocol feature the APK
   has vs. what our driver (`D:\glanceos\idotmatrix`) currently implements.
   Start here to see the whole landscape.
3. **[APK_PROTOCOL_FINDINGS.md](APK_PROTOCOL_FINDINGS.md)** — byte-level detail
   for driver gaps (verify_password, set_time_indicator, delete_device_data,
   screen-timeout, DIY mode names, graffiti mirror hypothesis).
4. **[ALARM_BUZZER_APK_FINDINGS.md](ALARM_BUZZER_APK_FINDINGS.md)** — byte-level
   detail for the Timer/Schedule (alarm+buzzer) subsystem specifically.

Source: decompiled `com.tech.idotmatrix` APK at
`C:\Users\Madhat\Downloads\com.tech.idotmatrix.apk_Decompiler.com\sources\`.
All three research docs cite exact file paths and line numbers — no re-searching
the APK should be needed for anything listed.

## Ground rules

- **Nothing in our current driver has been changed by this research.** Every
  finding is "here's what the bytes/ack should be" — verification and porting
  are separate, deliberate steps.
- **Byte-identical confirmation, not assumption.** Every "confirmed" claim in
  the docs was checked against either (a) our existing hardware-verified code,
  or (b) an exact string/byte match across two independent sources (old lab
  fork + current 2026 APK). Where confidence is lower, the docs say so
  explicitly ("hypothesis", "needs hardware test").
- **fa03 is the oracle.** Every new command should be tested with a response
  listener attached (`protocol/response.py` / `client.add_response_listener`)
  — accepted (`status=1`) vs rejected (`status=0`) vs silence (unrecognized)
  tells you immediately whether a guessed byte layout is even in the right
  neighborhood, before worrying about whether the visual effect is correct.

## Priority order

1. **Port the four confirmed-safe additions** (`APK_PROTOCOL_FINDINGS.md` §1-4):
   `verify_password`, `set_time_indicator`, `delete_device_data`,
   screen-timeout. All are small, flat, single commands in the same shape as
   existing `protocol/common.py` builders. Gate `set_time_indicator` and
   `delete_device_data` as experimental per standing project decision.
2. **Add the `DiyImageFun` named constants** to `protocol/image.py` (modes 2/3
   are currently unnamed magic numbers the device already accepts). Zero risk —
   it's naming, not new bytes.
3. **Hardware-test the two DIY-mode hypotheses** that could remove the
   black-flash-on-connect behavior: `ENTER_NO_CLEAR_CUR_SHOW` (mode 3) and
   `QUIT_STILL_CUR_SHOW` (mode 2). Directly useful for the Presenter's
   flash-free transition goal.
4. **Hardware-test graffiti mirror values 0-4** against the `DiyImageMoveType`
   labels (`NO_EFFECT`/`HORIZONTAL_MIRROR`/`VERTICAL_MIRROR`/`OVERALL_MOVEMENT`/
   `ERASE`) — see `APK_PROTOCOL_FINDINGS.md` §5 for why this is a hypothesis,
   not a confirmed mapping, and why the existing working code should not be
   changed before this test.
5. **Timer + Schedule (alarm/buzzer)** — full byte layouts in
   `ALARM_BUZZER_APK_FINDINGS.md`, its own suggested verification order
   (flattest/smallest commands first).
6. **Everything in `FEATURE_MATRIX.md`'s "not planned" section** — explicitly
   out of scope (cloud, OTA/firmware, native-AES-blocked location, video/camera
   constants that have no real feature behind them). Don't spend time here
   without a product reason to revisit the decision.

## What's deliberately not chased further

- **Location** (`get_device_location`): the AES key lives in a native `.so`
  (`csh.tiro.cc.aes`, JNI), invisible to APK decompilation. Would need ARM/x86
  binary reverse-engineering or live BLE traffic capture — a different kind of
  project. Closed, not "someone should look harder at the Java."
- **The paint-stroke DIY protocol** (`SendCore.sendDiyImageData`) and **the
  second mic command** (`sendMicCommand1`) are documented for completeness but
  not recommended — our existing `graffiti`/`set_pixels` and `music_sync`
  already cover what GlanceOS needs.
- **Multi-panel-size text** (`TextAgreement.sendTextTo{832,1616,3232,1664,6464}`)
  — see `FEATURE_MATRIX.md` note. GlanceOS targets one panel size at a time via
  `ScreenSize`, so this is a "confirm we're using the right variant for 32x32"
  task, not a "port five renderers" task.
