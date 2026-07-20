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

## Mission

This project has **two equally important goals**:

1. **Provide the definitive Python SDK for iDotMatrix BLE displays** — a clean,
   typed, async-first API that makes controlling a panel feel like controlling
   a device, not constructing packets.
2. **Become the reference implementation and documentation of the device
   protocol** — every verified reverse-engineering discovery lands here, every
   unverified one is clearly marked, and the repository is the authoritative
   record of how this hardware actually behaves.

Protocol research is as valuable a contribution as code. A probe log that
proves what a mystery byte does advances the mission exactly as much as a new
feature.

**Core design principle — protocol correctness takes precedence over
convenience.** The SDK faithfully exposes and documents device behaviour, even
when the firmware behaves unexpectedly. It does not hide, normalize, or
silently compensate for protocol quirks without documenting them: an ack that
lies is documented as an ack that lies.

---

## Protocol maturity at a glance

One-line status per subsystem (details and evidence in §3; tags per the
conventions above):

| Subsystem | Maturity | One-liner |
|---|---|---|
| BLE transport | ✅ | connect/reconnect/acks/notifications; WinRT stale-session self-heal; hardware-proven under soak |
| Protocol builders | ✅ | byte-exact, tested; a handful of unexplained magic bytes remain (§5) |
| Framebuffer (DIY) | ✅ | full-frame + entry/quit modes hardware-mapped, incl. mode-3 failure quirk |
| Graffiti (partial updates) | ✅ | delta path proven; "mirror" byte is a documented firmware quirk |
| Images (adapt + show) | ✅ | SDK-side pipeline solid; no dithering/gamma yet (§6) |
| GIF (upload + native playback) | ✅ | chunked handshake proven; 64-frame/2 s SDK-side caps |
| Clock (native) | ✅ | 8 styles; ticks on RTC through disconnects; never flash-persists |
| Text (native) | ✅ **verified** | full saga 2026-07-20: the “NACK” was our own ack misparse (fixed); `sendTextTo3232` ported — render A/B proved the generic packet TRUNCATES on 32×32 while the 32×32 variant renders fully; packet speed byte measured (100 = smoothest marquee) |
| Effects / color | ✅ *(simplified)* | works; APK has a richer command (real speed/saturation) unported |
| Countdown / stopwatch / scoreboard | ⚠ | source-confirmed, not yet hardware-verified |
| Alarm (Timer slots) | ✅ | chunked upload + GIF/image content + buzzer proven live |
| Weekly schedule | ⚠ | upload + firing proven; week-bit mapping and PNG content unverified |
| Music sync | ⚠ | kept for parity; app itself doesn't use it |
| Eco / device settings | ⚠ | source-confirmed; screen-timeout family dead on 32×32 |
| Experimental namespace | ❓/⚠ | verify_password, time-indicator, delete-device-data (destructive) |
| Simulator | ✅ *(partial fidelity)* | framebuffer semantics faithful; no ack/DIY-mode modeling yet (§7) |

---

## Contributor philosophy

**Reverse engineering is a first-class contribution.** The following are as
valuable as production code, and the contribution docs will say so explicitly:

- hardware probes (and their logs — negative results count)
- BLE packet captures of the vendor app
- firmware/model behaviour comparisons (16×16 / 32×32 / 64×64)
- APK analysis of new app releases
- protocol documentation and corrections
- behaviour verification of ⚠-tagged features on real panels

The capability table (§8) is community-maintained by construction: a
contributor with a panel we don't have moves features from ⚠ to ✅ without
writing a line of SDK code.

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
  feature shipped broken on 32×32 precisely because of this (§4, §16).
- Repo hygiene for a public debut: no CI, no lint/type config, no examples/,
  no CONTRIBUTING/CHANGELOG, committed build artifacts, README that references
  the monorepo.
- Four near-identical chunked-upload header builders; simulator can't exercise
  the upload handshake at all (§5, §7).

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

### 2.4 Why this shape — alternatives considered

The namespace-façade design was weighed against the common alternatives:

- **Flat client methods** (`client.set_brightness()`, `client.show_gif()`,
  `client.arm_alarm()`, … ~60 methods on one class): discoverable only until it
  isn't — autocomplete becomes a wall, related parameters drift apart, and
  every new protocol discovery bloats the same class. Namespaces give
  autocomplete a two-level shape (`client.<subsystem>.<verb>`) that matches how
  users think ("I want to do something with *text*") and lets ⚠ features live
  visibly quarantined in `.experimental` rather than interleaved with stable
  ones. Scalability matters here: §9's missing-capability list *will* land
  eventually, and a flat class would absorb it badly.
- **Command-object APIs** (`client.send(SetBrightness(60))`): maximally
  protocol-faithful and great for middleware, but hostile to discovery (you
  must know the command class exists), verbose for the 90% case, and it
  exports the packet vocabulary as public API — freezing internal protocol
  naming into the compatibility contract. We keep command objects *internal*
  (builders) and expose verbs.
- **Protocol-centric APIs** (thin wrappers named after APK internals:
  `client.mutil_color(...)`, `client.diy_fun(mode=3)`): perfect fidelity,
  terrible ergonomics — the vendor's obfuscated naming becomes our UX. The
  layered design already preserves fidelity where it belongs (protocol modules
  keep protocol names, byte-exact tests pin them); the façade translates to
  human vocabulary exactly once.

The namespace façade is therefore not a style preference: it is the only shape
of the three that simultaneously (a) survives protocol growth without API
churn, (b) keeps experimental surface visibly separated (a safety property on
hardware that acks lies), and (c) lets protocol naming stay protocol-accurate
underneath a stable human-facing vocabulary.

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
| Device-rendered scrolling text (9 modes, 6 color modes) | ✅ **verified 2026-07-20** | Full arc, worth reading as a protocol lesson: (1) the 2026-07-19 “rejection” was our parser misreading StatusAck SAVED (3) as a boolean nack — fixed, (0x03,0x00) joined the StatusAck families; (2) `sendTextTo3232` ported — sole wire diff vs the generic sender is one row-family metadata byte; (3) render A/B on a real 32×32: the generic packet renders TRUNCATED (“HELLO”→“HEL”), the 32×32 variant renders fully; (4) packet speed byte governs marquee smoothness (50 choppy / 95 / 100 smoothest); the separate set_speed command has NO effect on live text. |
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

**Future host-side rendering investigations** — none of these exist today;
all would be SDK-side (Pillow/NumPy) work sitting strictly *above* the protocol
layer, which stays raw-RGB888-in-bytes-out regardless:

- **Anti-aliasing**: for text, requires moving off the 1-bit device-text path
  (firmware colorizes a binary mask — AA is structurally impossible there) to
  SDK-rasterized text pushed as frames; for shapes, straightforward once a
  drawing helper exists.
- **Dithering**: optional Floyd–Steinberg (or ordered) when palettizing photos
  — today `dither=NONE` is hardcoded; pixel art must keep it off.
- **Gamma correction**: LEDs are not sRGB; a configurable gamma LUT before
  upload.
- **LED color calibration**: measured on hardware that design-tool colors shift
  visibly (e.g. a mid-green renders cyan on the reference 32×32 panel). A
  per-panel calibration profile (even a simple 3×1D channel LUT) is the fix;
  needs a calibration probe methodology first — ❓ research, not implementation.
- **High-quality text rasterization**: SDK-side text-to-frame rendering
  (any font, AA, kerning, per-glyph color) as a *complement* to native device
  text, not a replacement — native text animates device-side and survives
  host sleep; SDK text is one static frame unless the host animates it.
- **Interpolation improvements**: LANCZOS for photographic GIF frames
  (currently NEAREST unconditionally); per-content-type filter choice.
- **Rendering profiles**: a named `pixel_art` profile (NEAREST, no dither, no
  gamma) vs `photo` profile (LANCZOS, dither, gamma/calibration) so callers
  choose intent once instead of five knobs.

These are investigation items, not commitments; each graduates through the
normal ⚠→✅ process with visual verification on hardware (a preview PNG is not
proof — the panel is).

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

**Recommendation: GPL-3.0-or-later — the appropriate license given the
currently documented lineage.**

Basis: our protocol builders are documented in-source as "ported verbatim"
from lab code whose byte layouts came from studying 8none1's work and the
derkalle4 lineage; derkalle4's `idotmatrix` library is **GPLv3** (PyPI
metadata, checked 2026-07-20); pyproject already declares `GPL-3.0-or-later`.
With that provenance on record, GPL is the honest and defensible choice for
this release — a permissive license would require provenance work that hasn't
been done. Protocol *facts* aren't copyrightable, but code *expression*
lineage matters, and the current documentation points to GPL.

This is a recommendation grounded in today's documented provenance, not an
immutable conclusion: a future clean-room reimplementation of the derived
expression (built strictly from the protocol documentation this repo
maintains) could in principle support a permissive license. That effort is
explicitly out of scope for this project's roadmap — noted only so the door
is documented, not welded shut.

Actions: LICENSE file (GPL-3.0-or-later) in-repo; README credits section naming
the full chain (8none1 → derkalle4/python3-idotmatrix-client → markusressel/
idotmatrix-api-client → this SDK); keep per-module credit comments; add the two
missing lineage names (currently only 8none1 is credited anywhere).

---

## 14. Naming recommendation

PyPI reality (verified 2026-07-20): `idotmatrix` **taken** (derkalle4, GPLv3,
v0.0.9 Apr 2025 — the incumbent users find first); `idotmatrix-sdk` **taken**
(unrelated, v0.1); `pyidotmatrix` **available**; `idotmatrix-ble` **available**.

The sharper problem is the **import namespace**, and it is confirmed, not
assumed: the incumbent's own README imports `from idotmatrix import
ConnectionManager`, and its repo's package directory is `idotmatrix/`
(verified against the project source, 2026-07-20) — the same top-level package
name we use. Two distributions installing the same top-level package into
site-packages overwrite each other's files: **coexistence is genuinely
impossible**, not merely confusing. And coexistence will be demanded — Home
Assistant users often have the incumbent installed.

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

## Engineering & performance goals (long-term)

Goals, not implementation requirements — they steer design reviews, they don't
gate releases:

- **Minimal allocations on the hot path**: frame/delta packet construction
  should reuse buffers where practical; a 1 fps clock should not churn the GC.
- **Predictable memory usage**: bounded queues (the latest-wins mailbox
  pattern), no unbounded frame backlogs — the device drains at ~0.67 fps and
  the SDK must never buffer what the device can't consume.
- **Async-friendly by construction**: no blocking I/O or sleeps inside the
  event loop; anything that waits, awaits.
- **Efficient framebuffer uploads**: exploit the measured cost model
  (full frame ≈ 1.5 s acked; graffiti pixel ≈ 20 ms) — helpers should make the
  cheap path (deltas) the natural path.
- **Sustained animation support**: a consumer should be able to run GIF-rate
  or delta-driven animation indefinitely without drift, leaks, or device-side
  queue collapse (soak-test evidence: 24 h+ at ~1 fps, flat memory).
- **Minimal transport overhead**: respect negotiated MTU, chunk exactly once,
  never re-encode payloads that are already wire-shaped.
- **Streaming: BENCHMARKED 2026-07-20** (probes/probe_streaming_benchmark.py,
  operator at a real 32×32; motivated by
  [IDotMatrixXLedFx](https://github.com/suchyindustries/IDotMatrixXLedFx)'s
  24–28 fps send-rate logs and
  [idotmatrix-overclocked](https://github.com/pracucci/idotmatrix-overclocked)'s
  playable 64×64 games). Measured: acked full frames = 1.25–1.35 fps, and the
  bottleneck is the write-with-response round trips themselves — dropping the
  ack *wait* alone changes nothing (1.30 fps). Write-WITHOUT-response is
  honored by our variant (LumiSync's notes report it ignored on theirs — a
  firmware difference) and ingests 167 fps at the radio, but **the panel
  renders full DIY frames at a hard ~1.75 fps cap regardless of send rate**,
  sampling the latest frame and dropping the rest; its fa03 notifies track
  frames *processed*, not received. Sustained flooding dropped the BLE link
  twice. Design consequence: an unacked frame path is worth ~40% render rate
  plus non-blocking sends (~20 ms vs ~740 ms per frame), but real animation on
  this hardware belongs to the graffiti delta path (≤255 px in ~20 ms,
  unacked — ~50 cmd/s), not full frames. Service map from the same session:
  our variant exposes the `ae00`/`ae01`/`ae02` UART service but neither
  LumiSync's version-read characteristic nor the Telink `fee9` OTA service.

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
audit clean.* *Status 2026-07-20: ✅ CLOSED — extraction done (subtree split,
full history), LICENSE/NOTICE/credits in place, RE docs migrated to
docs/reverse-engineering/, CONTRIBUTING + CI workflow added, fresh-venv
install verified green.*

**SDK-M2 — API stabilization (the one breaking pass)**
Package rename (§14) · namespace renames (`device`, `stopwatch`, `alarms`,
`media`) · `discover()` → `DeviceInfo` · async context manager · exception
hierarchy + reject-raises-by-default · command serialization lock · typed
callbacks. *Accept: greenfield examples in §2.2 run verbatim; mypy clean.*

*Status 2026-07-20 — additive half DONE:* package rename, `discover()` →
`DeviceInfo`, async context manager + `connect_to()`, exception hierarchy
(`exceptions.py`), and reject-raises-by-default in `_send` (with a
`verify_commands` escape hatch; `verify_password` stays fire-and-forget because
its (5, 2) ack key collides with graffiti's nack — see the call-site note).
*Deliberately deferred to just before PyPI publish:* the namespace renames
(`device`/`stopwatch`/`alarms`/`media`), mapping transport failures to
`ConnectionLostError`, serialization lock, and typed callbacks — the monorepo
driver still evolves against the old names, and renaming now would turn every
cross-repo sync into a rename-translation exercise for zero user benefit before
the first published release.

**SDK-M3 — Protocol completeness & verification**
Port `sendTextTo3232` (unblocks text — the known-broken feature) · unify the 4
chunked builders · full effects command · verify_password probe · week-bit +
`patch()` verification · capability table implemented. *Accept: text renders on
32×32; capability table consulted by all ⚠ paths.*

> ⚠ **Maintainer ruling (2026-07-20): the `verify_password`/`set_password`
> probe is sequenced LAST across the entire roadmap** — after every other
> milestone's hardware work is done. A wrong guess about the password
> protocol's semantics could lock a panel out of its own driver, and there is
> no known factory-reset path. If you probe this on your own device, you
> accept that risk; do not treat it as an ordinary M3 item.

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

## 18. Open questions — ALL DECIDED (maintainer sign-off 2026-07-20)

1. **License: GPL-3.0-or-later — FINAL** (closes the MIT question, per §13's
   provenance basis).
2. **Name: `pyidotmatrix`** — distribution and import namespace both
   (collision with the incumbent verified impossible to avoid otherwise, §14).
3. **Repo home: `github.com/Madhat69/pyidotmatrix`.**
4. **Hardware verification: community probes cover 16×16/64×64** — accepted;
   the capability table + probe checklist are the contribution mechanism.
5. **GlanceOS pins the SDK version** once the package is published
   (`>=0.x,<0.y` until 1.0). Until then the monorepo copy remains GlanceOS's
   source of truth and changes are synced to the standalone repo manually.

---

## Long-term vision

Success looks like this:

- **The SDK developers naturally discover first** when they search for a
  Python library for iDotMatrix displays — because the docs answer their
  question in the first minute and the capability table tells them the truth
  about their panel.
- **The reference implementation of the protocol** — when someone asks "what
  does byte 23 mean," the answer is a link into this repository.
- **The authoritative source for hardware behaviour** — probe evidence, ack
  semantics, persistence rules, and firmware quirks documented nowhere else,
  maintained by a community that treats a good packet capture as a first-class
  pull request.
- **A stable public API over evolving protocol knowledge** — discoveries keep
  landing (experimental → verified → stable) without ever breaking the code
  that early adopters shipped.

When a future project we cannot imagine yet — a game, an art installation, a
factory dashboard — picks this SDK without hesitation and finds that the
hardware does exactly what the documentation said it would, the mission is
accomplished.

---

*Prepared as the pre-implementation deliverable required by the SDK brief.
No code was changed. Implementation begins only after this document is approved.*
