# idotmatrix SDK — Architecture Review & Roadmap

**Status: DRAFT for review — no implementation until approved.**
Prepared 2026-07-20. Scope: the `idotmatrix` package (today a subdirectory of the
GlanceOS monorepo) as it prepares to become a standalone public repository — the
first public release, intended to be the reference Python SDK for iDotMatrix BLE
LED displays.

Evidence conventions used throughout:

- ✅ **Hardware-verified** — observed on a real panel, with the probe/date cited.
- ⚠ **Experimental** — decoded and source-confirmed from the vendor APK, but not
  verified on hardware (or verified *broken*, where flagged).
- ❓ **Reverse engineering in progress** — existence known; wire format partial
  or unknown.

Primary hardware reference: one 32×32 panel (name prefix `IDM-`), APK
`v2.1.2 googleRelease (2026-06-29)`. All claims cite a probe script, an APK
research doc, or a dated hardware session.

---

## 1. Executive summary

**Strengths (keep these):**

- The layered architecture is genuinely clean: pure protocol builders → transport
  (reconnect/acks/notifications) → display backends → feature-namespace façade.
  Zero application coupling (verified: no `glanceosd` imports anywhere).
- Byte-exact protocol tests (13 files, ~1,900 lines) and a real hardware-probe
  culture (`probes/`, 8 scripts) — the RE evidence ships with the code.
- Hardware knowledge is unusually deep and already written down: ack semantics,
  DIY-mode quirks, chunked-upload handshakes, endianness corrections, firmware
  rejections. Few device SDKs launch with this much verified truth.
- The public surface is small, typed, and explicit (`__all__` of 13 names).

**Weaknesses (fix before/at first release):**

- **Licensing is incomplete**: no LICENSE file in-package, attribution chain
  names only one of three upstream lineages. This is a GPL correctness issue,
  not polish (§13).
- **Naming collision**: our import name `idotmatrix` collides with the incumbent
  PyPI package `idotmatrix` (derkalle4). The one moment to fix this is now (§14).
- The device can **reject a command while the SDK reports success** — acks are
  parsed but rejection is not surfaced as an error at the API layer. The text
  feature shipped broken on 32×32 precisely because of this (§4, §6).
- Repo hygiene for a public debut: no CI, no lint/type config, no examples/,
  no CONTRIBUTING/CHANGELOG, committed build artifacts, README that references
  the monorepo.
- Four near-identical chunked-upload header builders; simulator can't exercise
  the upload handshake at all (§6, §8).

---

## 2. Public API review (Review 1) and greenfield design (Addendum 1)

### 2.1 What exists

```python
client = IDotMatrixClient(ScreenSize.SIZE_32x32, mac_address="AA:BB:...")  # or None → first discovered
await client.connect()
await client.common.set_brightness(60)
await client.clock.show(style=0, hour24=True)
await client.gif.upload_file("nyan.gif")
await client.display.show_frame(rgb_bytes)      # DIY framebuffer
await client.display.set_pixels((255,0,0), [(0,0),(1,1)])
await client.disconnect()
```

Judged against the brief's criteria: **intuitive** (feature namespaces read
well), **discoverable** (autocomplete over namespaces works), **Pythonic**
(async-first, typed), **internally consistent** (one transport, one ack
contract). It is genuinely close to right. The issues are at the edges:

1. **Discovery returns bare MAC strings** (`discover_devices() -> list[str]`).
   Users must know to glue a MAC into the constructor.
2. **No async context manager** — every example needs try/finally to guarantee
   disconnect.
3. **Namespace names leak protocol jargon**: `chronograph` (users say
   *stopwatch*), `common` (a junk drawer: brightness, power, time, password,
   reset), `ExperimentalFeature.timer_set` (users say *alarm*).
4. **Rejection is silent**: `fa03` nacks are parsed (`DeviceAck.accepted=False`)
   but nothing raises. The 32×32 text rejection (§4) proved this can hide a
   fully broken feature. `await_device_ack` exists but is opt-in and manual.
5. **No exception hierarchy**: callers get `ValueError`, `BleakError`, or
   `ChunkedUploadError` with no common base.
6. `__init__.py` docstring drifts from `__all__` (minor).
7. `add_listener` callbacks are untyped; no `py.typed` marker, so *all* typing
   is invisible downstream.

### 2.2 Greenfield: what the API should feel like

Namespace hierarchy (rationale beside each):

```
IDotMatrixClient
├── .device          # identity & device settings: brightness, power, time sync,
│                    # flip, password, reset  («common» renamed — a user thinks
│                    # "device settings", not "common")
├── .display         # framebuffer: show_frame, set_pixels, freeze  (unchanged —
│                    # this is the pixel surface)
├── .media           # prepared content: show_image, show_gif  (today spread
│                    # between client.show_image and client.gif — one home for
│                    # "put this file on the panel")
├── .text            # device-rendered text (modes, speed, color)
├── .clock           # native clock face
├── .stopwatch       # alias of chronograph  (protocol module keeps its name;
│                    # the user-facing name matches what users search for)
├── .countdown
├── .scoreboard
├── .effects         # native effects + fullscreen color
├── .music           # onboard-mic music sync
├── .alarms          # Timer slots: arm/disarm with GIF/image content + buzzer
│                    # (graduates OUT of experimental — upload path is ✅)
├── .schedule        # weekly schedule themes (stays ⚠ until week-bit verified)
└── .experimental    # unverified/destructive: delete_device_data,
                     # set_time_indicator, screen_timeout, verify_password
```

Usage, end to end (the brief's checklist):

```python
from idotmatrix import discover, IDotMatrixClient, ScreenSize

# discover devices — rich objects, not bare strings
devices = await discover()                  # [DeviceInfo(name="IDM-A03EAF", address="6D:FD:...", rssi=-52)]

# connect / disconnect — context-managed
async with IDotMatrixClient.connect_to(devices[0], ScreenSize.SIZE_32x32) as dm:
    await dm.device.set_brightness(60)                      # brightness
    await dm.device.sync_time()                             # RTC ← host clock
    await dm.media.show_image("photo.jpg")                  # resize/letterbox → framebuffer
    await dm.media.show_gif("nyan.gif")                     # adapt + chunked upload
    await dm.text.show("HELLO", mode=TextMode.MARQUEE, color=(0,255,0))
    await dm.display.show_frame(raw_rgb)                    # full framebuffer
    await dm.display.set_pixels((255,0,0), [(0,0),(1,1)])   # partial update
    await dm.display.draw() ...                             # (post-1.0: lines/rects via graffiti batching)
    await dm.countdown.start(minutes=5)                     # native countdown
    await dm.stopwatch.start(); await dm.stopwatch.pause()  # native stopwatch
    await dm.alarms.arm(slot=8, hour=7, minute=30, buzzer=True, content=gif_bytes)
    await dm.schedule.set_theme(...)                        # ⚠ experimental
    await dm.music.enable()                                 # onboard-mic visualization
# disconnect happens on exit, even on exceptions
```

**Error model**: one hierarchy, and rejection becomes loud —

```
IDotMatrixError
├── ConnectionLostError          # transport-level
├── CommandRejectedError         # fa03 nack correlated to a sent command
├── UploadError                  # chunked-upload FAILED/timeout (today's ChunkedUploadError)
└── UnsupportedFeatureError      # known-broken on this firmware (e.g. text on 32×32 today)
```

Commands that have a known ack key await it by default (bounded timeout) and
raise `CommandRejectedError` on nack. Fire-and-forget stays available via
`wait_for_device=False`. This single change would have caught the 32×32 text
failure in the first integration test instead of on a user's panel.

### 2.3 Diff vs existing, and what must happen pre-1.0

| Change | Why now (pre-release) |
|---|---|
| Rename import package (see §14) | Import-name collision with incumbent; impossible to fix after release |
| `common` → `device`; add `stopwatch`/`alarms` user-facing names | Renames are free before the first user exists; protocol modules keep protocol names |
| Async context manager + `discover()` returning `DeviceInfo` | Entry-point ergonomics define first impressions |
| Exception hierarchy + reject-raises-by-default | Correctness: silent rejection already shipped one broken feature |
| `py.typed` + typed callbacks | Zero-cost now; downstream type-checking forever |
| `media` namespace consolidating `show_image` + gif | Cohesion; keeps the client façade small |

Everything else (drawing helpers, capability flags, CLI) is post-1.0 and must
not block release. Back-compat: since no public users exist yet, aliases from
old names are unnecessary — one clean break now, then stability (§15).

---

## 3. Capability inventory (Review 2)

Status tags per §"Evidence conventions". Evidence: probe scripts live in
`probes/`; APK docs live in the research lab (`FEATURE_MATRIX.md`,
`APK_PROTOCOL_FINDINGS.md`, `APK_SECOND_PASS.md`, `ALARM_BUZZER_APK_FINDINGS.md`).

### Device
| Capability | Status | Notes / evidence |
|---|---|---|
| Discover (BLE scan, `IDM-` prefix) | ✅ | `discover_devices()` |
| Connect / disconnect / auto-reconnect | ✅ | incl. WinRT stale-connection self-heal (2026-07-18: reconnect-and-retry on `WinError -2147023673`) |
| Connection status + transport events/snapshot | ✅ | `TransportSnapshot`, event listeners |
| Brightness (5–100%) | ✅ | out-of-range nacked by device (fa03) |
| Power on/off | ✅ | |
| RTC time sync | ✅ | required before alarms/schedules fire correctly |
| Screen flip | ⚠ | source-confirmed; unverified on our panel |
| Password set | ⚠ | byte-4 mode field hardcoded `1`, unexplored |
| Password verify | ⚠ | ack shape unobserved; (5,2) collision risk (§6) |
| Screen timeout set/read | ⚠ | **no fa03 ack, no visual effect on 32×32** (2026-07-12) — likely model-specific; units unknown |
| Firmware/device info query | ❓ | no known command; RE target |
| Reset | ✅ | `common.reset()` — used live 2026-07-18 (cleared a stuck state) |
| Delete device data | ⚠ **destructive** | byte-identical across APK versions; never sent to hardware; requires `confirm=True` |

### Display (framebuffer)
| Capability | Status | Notes |
|---|---|---|
| Full frame upload (DIY) | ✅ | ~1.5 s device processing; ack = flow control |
| Partial pixel updates (graffiti) | ✅ | ~20 ms unacked; draws over framebuffer; ≤255 px/command (found by testing) |
| DIY entry mode 1 (clear+show) | ✅ | always takes; black flash |
| DIY entry mode 3 (no-clear) | ✅ *(as a caveat)* | **silently fails over effect/clock states — device acks anyway** (A/B 2026-07-17; 3-run clock probe 2026-07-19) |
| DIY quit mode 2 (keep frame) | ✅ | kept frame **survives clean disconnect** (2-run probe 2026-07-18); does NOT survive power-cycle |
| Freeze screen | ⚠ | source-confirmed |
| Fullscreen color | ✅ | flash-persists across power-cycle (survived 3 days, 2026-07) |
| Native persistence by mode kind | ✅ | effect ✅ / color ✅ / clock ❌ / DIY ❌ (persistence probes 2026-07-17) |
| Panel join (multi-panel) | ❓ | bytes match APK; purpose unknown *upstream too* |
| Graffiti "mirror" byte | ✅ *(as quirk)* | values 0/1/2/4 identical, 3 nacked `[5,0,5,2,0]` (2026-07-12); no counterpart in current APK send path |

### Text
| Capability | Status | Notes |
|---|---|---|
| Device-rendered scrolling text (9 modes, 6 color modes) | ⚠ **broken on 32×32** | device nacks `type=3 sub=0` for all modes (probe 2026-07-19). Our packet is the *generic* variant; APK uses per-size `sendTextTo832/1616/3232/1664/6464`. Fix = port `sendTextTo3232`. **SDK-blocker for the text feature.** |
| Font rendering (host-side rasterization) | ✅ *(code path)* | 16×32 1-bit cells, caller-supplied TTF; no AA, fixed cell width |
| Preset phrase slots (`PhraseAgreement`) | ❓ | app feature; wire format unmapped |

### Images / Animation
| Capability | Status | Notes |
|---|---|---|
| Image adaptation (FIT/FILL/STRETCH, palettize, alpha→bg composite) | ✅ | SDK-side (Pillow); details §7 |
| GIF upload + native playback | ✅ | chunked, `optimize=True` required; 64-frame / 2 s caps SDK-side |
| Static non-DIY image path (`ImageAgreement`) | ❓ | separate APK path, never investigated |
| Video/Camera types | ❓ | vestigial constants in APK; no UI, likely dead |

### Native modes
| Capability | Status | Notes |
|---|---|---|
| Clock (8 styles, date/24 h flags, color) | ✅ | ticks on RTC through disconnects; **not** flash-persisted |
| Countdown | ⚠ | source-confirmed; runs autonomously on device |
| Stopwatch/Chronograph | ⚠ | source-confirmed |
| Scoreboard (0–999 ×2) | ⚠ | source-confirmed |
| Effects (7 styles, 2–7 colors) | ✅ *(simplified)* | our builder hardcodes speed byte `90`; APK's `MutilColorAgreement` has real speed/saturation + bespoke 96-byte chunking (§10) |
| Eco mode (scheduled dimming) | ⚠ | source-confirmed |
| Music sync (onboard mic) | ⚠ | app doesn't reference it; kept for parity |

### Alarms (Timer) & Weekly Schedule
| Capability | Status | Notes |
|---|---|---|
| Alarm slots (10), arm with content + buzzer | ✅ | chunked upload handshake proven; fires with clock-interlude ritual (2026-07-12) |
| Alarm GIF content | ✅ | renders animated + buzzer |
| Alarm raw-RGB image content | ✅ | renders once header endianness fixed (LE, 2026-07-12 evening) |
| Alarm text content | ❓ | `textSolve` offsets untrustworthy in decompile; needs live BLE capture |
| Alarm close/disarm | ⚠ | ack is a **state echo**, not accept/reject (statuses 0/1/3 observed from different states) |
| Week bitmask day mapping | ✅ *(partial)* | Sunday bit confirmed live; full table + Schedule `patch()` `+255/+256` question open |
| Schedule master switch | ⚠ | all 4 packed values accepted; bit semantics untested |
| Schedule theme upload (GIF) | ✅ | SAVED + fired in window (2026-07-12); **window ended ~1 min early — end boundary likely minute-exclusive** |
| Schedule image content (PNG, not raw RGB) | ⚠ | genuine asymmetry vs Timer; rendering untested |

### Diagnostics
| Capability | Status | Notes |
|---|---|---|
| fa03 ack stream (accept/reject) | ✅ | our discovery — upstream tried to READ a notify-only char |
| 3-way StatusAck (chunk handshake) | ✅ | duplicates occur; callers must tolerate |
| Ack correlation by (type,subtype) | ✅ *(with caveat)* | stronger than the APK's last-writer-wins; (5,2) collision documented (§6) |
| Reconnect events, write failures, snapshots | ✅ | |

---

## 4. Hardware knowledge doctrine (Review 3)

The observed behaviors below are **product documentation, not trivia**. Each
must survive into the public docs (Protocol Notes / Firmware Notes):

1. **Acks confirm receipt, not effect.** The device can accept a command and
   not do it (DIY mode 3 over an effect), or nack a command the SDK reported as
   sent (32×32 text). Every doc page about a ⚠ feature repeats this.
2. **Write-with-response is flow control.** Full frame ≈ 1.5 s processing;
   the ack is the "device done" signal. Unacked spam queues device-side and
   drains at ~0.67 fps; the device self-recovers.
3. **Chunked uploads**: 4096-byte chunks, per-chunk StatusAck
   (1=next, 3=saved, 0=failed), duplicates possible, single-chunk uploads jump
   straight to SAVED.
4. **Persistence is per mode kind** (effect/color persist; clock/DIY never), and
   *how a link ends matters*: clean disconnect reverts DIY in ~2 s, abrupt loss
   freezes the last frame indefinitely, and a mode-2 quit parks a kept frame
   that survives clean disconnects.
5. **Endianness**: every multi-byte Timer/Schedule header field is little-endian
   on the wire (the decompile's `short2Bytes` appears BE but call sites swap).
6. **Known firmware rejections on 32×32**: generic text packet; screen-timeout
   family (no ack, no effect); graffiti mirror=3.
7. Windows/WinRT: post-resume the stack can claim connected+services-resolved
   while the GATT session is dead — a robust consumer forces reconnect on
   first write failure (the SDK transport now self-heals this).

---

## 5. Protocol audit (Addendum 2)

Full audit performed module-by-module (18 modules). Highlights:

**Unexplained magic bytes (each is a small RE target):**
- `effect.py`: hardcoded `90` at the speed offset (real speed param exists in APK).
- `timer.py` byte 23 `(num+20)`, `schedule.py` byte 22 `(index+30)` — "second
  markers" in disjoint ranges; hypothesis: device-side content-slot ID space.
- `graffiti.py` byte 4: always 0, unknown.
- `common.build_delete_device_data`: trailing `12,0,1..11` literal, unexplained.
- `text.py`: `\x05\xff\xff\xff` char separator and trailing type byte `12`.
- `common.build_set_password` byte 4: APK passes a variable; we hardcode `1`.

**Duplicated implementations:**
- Four chunked-upload header builders (`image/gif/timer/schedule`) share an
  identical outer loop and independently re-implement length-prefix, total-size
  LE, and CRC32 — the single largest internal refactor target. (`bytes_.py`
  primitives themselves are cleanly shared; CRC calls split between
  `binascii.crc32` and `zlib.crc32` — unify.)
- Password 6-digit→3-byte encoding duplicated between set and verify.

**Orphans / dead paths:** `build_timer_week` and `build_schedule_week` are
public helpers never wired into the client; `build_schedule_text_packets` is a
deliberate `NotImplementedError` stub; `GIF_TYPE_DIY_ANIMATION=13` and the
whole `time_sign` path are unreachable from the public API.

**Known ack-correlation flaw:** pending-ack futures are keyed by
(type,subtype); `verify_password` expects key (5,2) and graffiti's rejection
nack is byte-identical `[5,0,5,2,0]`. A pending verify could be resolved by an
unrelated graffiti nack. The vendor app has *no* correlation at all, so ours is
an improvement, not a regression — but the limitation must be documented and
verify_password must not be interleaved with graffiti writes.

**Investigation priorities** (do not implement yet): (1) `sendTextTo3232`,
(2) effect speed byte, (3) verify_password ack shape, (4) schedule week-bit +
`patch()` off-by-one, (5) the two "second marker" bytes, (6) screen-timeout
units on a model that supports it.

---

## 6. Rendering audit (Addendum 3)

Three distinct rendering domains — the docs must never blur them:

**SDK-side (Pillow):**
- Still images: EXIF transpose → FIT/FILL/STRETCH resize (LANCZOS for photos,
  NEAREST when palettizing) → optional adaptive 256-color palettize
  (**dithering explicitly off**) → alpha composited onto a background color.
- GIF: frame extraction → NEAREST resize (unconditionally — photographic GIFs
  come out blocky), 64-frame cap, 2 s total-duration cap with even sampling,
  re-encode with `optimize=True` (required by the device).
- Text: per-char 16×32 1-bit rasterization from a caller-supplied TTF; no
  anti-aliasing, no kerning (independent fixed cells).

**Firmware-rendered:** native clock faces, effects, countdown/stopwatch/
scoreboard digits, GIF playback/looping, text animation modes + coloring
(the SDK ships 1-bit glyph masks; the device colorizes/animates).

**Protocol constraints:** raw RGB888 frames (no alpha on the wire), graffiti
color-per-command batching, GIF as a genuine encoded GIF bytestream.

**Gaps worth roadmapping:** optional dithering for photos; LANCZOS for GIF
frames; brightness/gamma compensation for LED response (design-tool colors do
not match panel output — measured on hardware); a documented "pixel-art path"
(NEAREST + no palette loss) vs "photo path" (LANCZOS + dither).

---

## 7. Simulator review (Addendum 4)

Verdict: **make it a first-class dev tool — it's 70% there.**

Faithful today: framebuffer semantics (full replace vs graffiti-over),
size/coordinate validation, connection listeners, optional timing emulation
(1.5 s frame / 20 ms pixel, from hardware measurements), frames-while-off.

Gaps: no image/PNG export (every consumer re-implements RGB→image); no DIY-mode
or ack modeling (the chunked-upload handshake and mode-3 quirk cannot be
exercised — tests against the simulator get false confidence exactly where the
hardware bites); introspection props are off-Protocol; `emulate_timing` is
untested and asymmetric.

Roadmap (SDK-M5): `to_image()`/`save_png()` export; optional ack emulation
(accept/nack/StatusAck sequences, duplicate-ack injection); a "quirk mode"
modeling mode-3-over-effect failure; document it as the CI workhorse.

---

## 8. Firmware compatibility (Addendum 5)

Known variation axes (all evidence 32×32 unless noted):

| Variation | Evidence |
|---|---|
| Per-size text senders (`sendTextTo832/1616/3232/1664/6464`) | APK; 32×32 rejects the generic packet (probe 2026-07-19) |
| Timer text font variant by `LedType` (8-row vs 16-row) | APK |
| Screen-timeout family unsupported on this 32×32 | probe 2026-07-12 |
| `set_time_indicator` "doesn't work" on some models (bytes identical in current APK) | lab note + APK |
| Graffiti byte-3 semantics (legacy/firmware quirk) | probe 2026-07-12 |
| Persistence-by-mode-kind table | probes 2026-07-17 |

**Strategy recommendation:** a static, versioned **capability table** in the SDK
(`capabilities(ScreenSize/model) -> frozenset[Capability]`), consulted by
feature namespaces to raise `UnsupportedFeatureError` early, and published as
the Hardware Compatibility doc. No runtime feature-probing (the device lies —
acks ≠ effect); the table is maintained from probe evidence. Contributors with
16×16/64×64 panels extend it via a documented probe checklist — this is how the
repo becomes the community's compatibility authority.

---

## 9. Missing-capability hunt (Addendum 6)

Ranked by confidence (wire-format completeness):

**HIGH (byte layout fully mapped — implementable next):**
1. `verify_password` — `[7,0,5,2,d1,d2,d3]`; ack shape needs one probe.
2. Screen timeout set/read — `[5,0,15,128,v]` + `0xFF` read sentinel; needs a
   supporting model to determine units.
3. `set_time_indicator` — `[5,0,7,128,0|1]`; experimental gating.
4. `delete_device_data` — mapped; keep destructive-gated.
5. **Full effects command** (`MutilColorAgreement`): real speed + saturation +
   bespoke 96-byte chunking — supersedes our simplified builder.
6. Alarm/Timer + Schedule already implemented; remaining HIGH work is the open
   verification list (week bits, close-ack vocabulary, Schedule PNG rendering).

**MEDIUM:** phrase slots (`PhraseAgreement` — feature real, bytes unmapped);
client-side dim-fade (`changeLight` formula confirmed: `byte*bright/100` —
enables smooth software fades).

**LOW:** live paint-stroke DIY protocol (`sendDiyImageData` — `set_pixels`
covers it); static non-DIY image path (`ImageAgreement`); second mic command;
video/camera types (likely vestigial).

**Blocked:** `get_device_location` (AES key in native `libAES.so`); cloud
(out of scope); OTA (out of scope — brick risk; the 0x00AE service is the OTA
channel per fbnlrz's independent RE, corroborating ours).

---

## 10. Repository structure & extraction plan (Review 4)

Structure is sound; no module renames recommended (brief's constraint honored).
Extraction checklist:

1. `git filter-repo` the `idotmatrix/` subtree out of the monorepo (preserves
   blame/history for contributors).
2. Add LICENSE (GPL-3.0-or-later) + NOTICE/credits (§13).
3. Scrub the 8 GlanceOS textual references (README lines 3–4/69; `__init__.py:10`;
   5 × "GlanceOS hardware" in client.py/common.py → "reference hardware").
4. Remove committed artifacts (`idotmatrix.egg-info/`, `.venv/`, `.pytest_cache/`)
   + proper `.gitignore`.
5. Migrate the research-lab docs the source cites (`APK_*.md`, `FEATURE_MATRIX.md`)
   into `docs/reverse-engineering/` — the source references them 8+ times; a
   standalone repo must carry its own evidence.
6. Verify `tests/Rain-DRM3.otf` redistribution license; replace with an OFL font
   if unclear.
7. Packaging: authors, `project.urls`, classifiers (License/Python/OS/Status),
   `py.typed`, exclude `probes/` from the wheel.

Layout additions: `examples/` (runnable scripts per capability), `docs/`,
`.github/workflows/`.

---

## 11. Testing roadmap (Review 5)

Today: strong byte-exact protocol coverage, transport tests, simulator tests.
Gaps and additions, in priority order:

1. **Regression suite for firmware truths**: encode every ✅ probe finding as a
   byte-exact test with the probe/date in its docstring (many exist; make the
   convention explicit and complete).
2. **Simulator-backed integration tests** once ack emulation lands (chunked
   upload happy/duplicate/failed paths, reject-raises behavior).
3. **Hardware verification suite** (`probes/` graduating into a structured,
   human-run checklist): one runner script per capability with PASS/FAIL
   prompts, per-model results recorded into the compatibility table. Keep
   fully separate from unit tests (never in CI).
4. **Edge cases**: max-size pixel batches, 64-frame GIF boundary, 4096-byte
   chunk boundaries, duplicate StatusAck tolerance, (5,2) collision guard.
5. CI matrix: Python 3.12–3.14, lint + mypy + pytest; no BLE in CI.

---

## 12. Documentation roadmap (Review 6)

Priority order (first four are release-gating):

1. **README** (rewritten standalone): pitch, install, 10-line quick start,
   capability table with status tags, link map.
2. **Getting Started / Quick Start** (docs/): discovery→connect→first image.
3. **Hardware Compatibility**: the capability table + how to contribute results.
4. **Protocol Notes**: the doctrine of §4 (acks, chunking, persistence,
   endianness) — this is the SDK's moat; nobody else documents this.
5. Architecture (the layer diagram + why opinion-free).
6. Public API reference (autodoc from types + docstrings).
7. Examples gallery (one runnable file per capability).
8. Firmware Notes (per-model quirks) + Reverse Engineering Notes (migrated APK
   docs + probe methodology).
9. Contributing (incl. "how to run probes safely") + Release Process.

---

## 13. License & attribution ruling

**Ruling: GPL-3.0-or-later. The MIT/Apache preference is not cleanly available.**

Chain of evidence: our protocol builders are documented in-source as "ported
verbatim" from lab code whose byte layouts came from studying 8none1's work and
the derkalle4 lineage; derkalle4's `idotmatrix` library is **GPLv3** (PyPI
metadata, checked 2026-07-20); pyproject already declares `GPL-3.0-or-later`.
A permissive relicense would require a per-module clean-room provenance audit
that the "verbatim" attributions already contradict. Protocol *facts* aren't
copyrightable, but code *expression* lineage is — and the honest reading is GPL.

Actions: LICENSE file (GPL-3.0-or-later) in-repo; README credits section naming
the full chain (8none1 → derkalle4/python3-idotmatrix-client → markusressel/
idotmatrix-api-client → this SDK); keep per-module credit comments; add the two
missing lineage names (currently only 8none1 is credited anywhere).

---

## 14. Naming recommendation

PyPI reality (checked 2026-07-20): `idotmatrix` **taken** (derkalle4, GPLv3,
v0.0.9 Apr 2025 — the incumbent users find first); `idotmatrix-sdk` **taken**
(unrelated, v0.1); `pyidotmatrix` **available**; `idotmatrix-ble` **available**.

The sharper problem is the **import name**: we also `import idotmatrix`, which
collides with the incumbent package on any machine that installs both. Shipping
that collision permanently forecloses coexistence — and coexistence is likely
(Home Assistant users often have the incumbent installed).

**Recommendation:** distribution **`pyidotmatrix`**, import **`pyidotmatrix`**.
One name everywhere, zero collision, discoverable (search "python idotmatrix"
matches literally), and the `py` prefix is a long-standing convention for
"the Python library for X". Runner-up: `idotmatrix-ble` (dist) — but its
natural import (`idotmatrix_ble`) is uglier and still invites confusion with
the incumbent's dist name. Decision point for the maintainer; the rename must
land before first publish (§2.3).

---

## 15. API stability policy (Addendum 7)

- **SemVer** from first public release. 0.x: minor may break with CHANGELOG
  notice. **1.0 = API freeze**: breaking changes only at major versions.
- **Deprecation**: deprecate in minor N (runtime `DeprecationWarning` + docs),
  remove no earlier than N+2 or the next major.
- **Experimental namespace policy**: everything under `.experimental` (and any
  method documented ⚠) is exempt from SemVer guarantees — explicitly stated in
  docs and docstrings.
- **Graduation process** (⚠ → stable): (1) wire format source-confirmed,
  (2) hardware-verified on ≥1 model with probe evidence recorded, (3) byte-exact
  regression tests, (4) documented in the capability table → then it moves out
  of `.experimental` in a minor release.
- **Compatibility table versioning**: firmware findings are additive data
  changes, never API breaks.

---

## 16. Independent review — findings not covered above (Addendum 8)

1. **The silent-rejection design flaw is the SDK's biggest correctness risk**
   (§2.2). It already shipped one broken feature. Fix pre-1.0.
2. **Concurrency is undefended**: two coroutines writing interleaved chunked
   uploads on one client would corrupt the handshake. Pre-1.0: either an
   internal per-client command lock or a documented "one command at a time"
   contract.
3. **`ScreenSize` is trusted, never validated**: connecting with the wrong size
   produces garbage frames with no error. RE target: identify size/model from
   the device (name suffix? a query command?); until then, document loudly.
4. **Testing blind spot**: nothing exercises `emulate_timing`, and no test
   drives `_send_chunked_upload` against duplicate/failed StatusAck sequences
   end-to-end (only unit-level parsing).
5. **Windows-specific resilience knowledge** (WinRT stale-GATT self-heal) is
   implemented but undocumented — it's a differentiator; surface it in
   Protocol Notes.
6. **Opportunity**: the probe methodology itself (fa03 subscription — which
   upstream never found) is publishable as a how-to; it's what will attract
   RE contributors, which is how the missing capabilities (§9) get filled.
7. **CLI**: a tiny `python -m <pkg> discover|show-image|text` would make the
   README demo-able in 30 seconds. SDK-M5, not release-gating.

---

## 17. Release milestones

**SDK-M1 — Repo extraction & licensing (release blocker #1)**
filter-repo extraction · LICENSE + NOTICE + full credits · GlanceOS-reference
scrub · artifact cleanup · packaging metadata + `py.typed` · migrate RE docs.
*Accept: fresh clone builds, tests green, zero monorepo references, license
audit clean.*

**SDK-M2 — API stabilization (the one breaking pass)**
Package rename (§14) · namespace renames (`device`, `stopwatch`, `alarms`,
`media`) · `discover()` → `DeviceInfo` · async context manager · exception
hierarchy + reject-raises-by-default · command serialization lock · typed
callbacks. *Accept: greenfield examples in §2.2 run verbatim; mypy clean.*

**SDK-M3 — Protocol completeness & verification**
Port `sendTextTo3232` (unblocks text — the known-broken feature) · unify the 4
chunked builders · full effects command · verify_password probe · week-bit +
`patch()` verification · capability table implemented. *Accept: text renders on
32×32; capability table consulted by all ⚠ paths.*

**SDK-M4 — Documentation**
The §12 list, items 1–8. *Accept: a newcomer goes zero→image-on-panel from docs
alone; every capability has a status tag.*

**SDK-M5 — Developer tooling**
CI (lint/mypy/pytest matrix) · examples/ · simulator export + ack emulation ·
optional CLI · CONTRIBUTING + probe checklist. *Accept: CI green badge; simulator
can run the upload handshake in tests.*

**SDK-M6 — API freeze**
Deprecation policy in effect · 0.9 release candidate on PyPI · call for testers
(other panel sizes) · compatibility table seeded with contributed results.
*Accept: no open API-shape issues; RC installs clean from PyPI.*

**SDK-M7 — 1.0**
CHANGELOG · release process doc · announcement (the RE notes are the marketing)
· 1.0 publish. *Accept: SemVer guarantees begin.*

---

## 18. Open questions (maintainer decisions needed)

1. Final sign-off on **GPL-3.0-or-later** (§13) — closes the MIT question.
2. Final name pick: **`pyidotmatrix`** recommended (§14).
3. GitHub org/repo home for the extraction.
4. Hardware access plan for verification milestones: currently one 32×32 panel;
   16×16/64×64 coverage will come from community probes — acceptable?
5. Should GlanceOS pin the SDK version immediately after extraction (recommended:
   yes, `>=0.x,<0.y` until 1.0)?

---

*Prepared as the pre-implementation deliverable required by the SDK brief.
No code was changed. Implementation begins only after this document is approved.*
