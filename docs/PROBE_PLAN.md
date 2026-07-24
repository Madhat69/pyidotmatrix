# Hardware Probe Plan — the open questions worth panel time

Living document. Maintainer adds/reorders freely; each entry says what we'd
learn, how, what it costs in panel time, and what it unblocks. Every session's
results get recorded in the probe's docstring + capabilities.py, per house
convention (asymmetric test patterns, attributed ack logging, operator
narrates — lessons of 2026-07-21).

**Standing exclusions — do not probe, regardless of list order:**
1. `set_password` / `verify_password` — LAST across the entire roadmap
   (maintainer ruling 2026-07-20: lockout risk, no known factory reset).
2. Writes to the `ae00`/`ae01` UART service — unknown factory/OTA-adjacent
   surface on a Telink SoC; blind writes risk bricking. Document-only until
   an HCI capture shows the vendor app itself using it (it likely never does).

---

## P1 — HCI snoop session: the app's actual bytes  ⭐ next session

**Why first:** one phone capture resolves several mysteries at once, including
the only capability where the vendor app beats us on our own panel.

Setup: Android Developer Options → enable **Bluetooth HCI snoop log** →
force-stop the app → reconnect → perform the scripted actions below in order,
noting rough timestamps → export `btsnoop_hci.log` (bug report zip or
`/sdcard/Android/data/...` depending on ROM) → we parse ATT writes to fa02
with Wireshark/pyshark and diff against our builders.

Scripted capture list (5–10 s each, in this order):
1. **Effect speed dial** — apply a stripes effect at 100%, drag ⚡ to ~0%,
   back to 100%. *Target: the unmapped speed wire path (our effect byte-5 and
   set_speed are both proven inert; app 100% is faster than anything we can
   send). Suspect: the 96/18 chunked framing our port of which the device
   ignores — capture also reveals the app's real effect-apply bytes, likely
   fixing `show_chunked`.*
2. **Brightness dial** drag — confirm it's our verified `set_brightness`.
3. **Text send** — type "HELLO WORLD", send. *Diff against our
   sendTextTo3232 port; captures the app's speed/color/mode defaults.*
4. **Paint screen strokes** — single dots + a drag stroke + any
   mirror/move tool the paint UI offers. *Target: SendCore.sendDiyImageData's
   5-byte-header envelope — the REAL home of the moveType byte; may explain
   graffiti byte-4 values 3 (OVERALL_MOVEMENT) and 4 (ERASE).*
5. **Music sync screen** — open it, make noise at the phone. *Hypothesis:
   the PHONE streams rhythm values (mic is app-side); would explain why our
   bare `send_image_rhythm` values drew nothing and stuttered the clock.*
6. **Clock styles** — cycle 2–3 styles, toggle 12/24h + date.
7. **Connect sequence itself** — the first packets after app connect.
   *Does the app send an init/handshake we don't (joint? freeze? a version
   query)? Might explain why some acked commands are inert for us.*
8. **DIY image upload** from gallery — chunk pacing, MTU negotiation packet.
9. If the app offers **eco / screen-timeout / power schedule** settings for
   this model: toggle each once.

Cost: ~20 min phone work + desk parsing. Unblocks: effect speed,
`show_chunked`, possibly music sync + graffiti move semantics + init quirks.

## P2 — GIF CRC cache (overclocked's claim)

Upload a GIF, wait, re-upload the identical bytes: does the second upload
return SAVED immediately with no NEXT_CHUNK round trips? Measure both wall
times and the ack sequences. If confirmed: instant GIF switching (device-side
cache keyed by CRC32) — directly powers GlanceOS M7 Stage 3's GIF takeovers
and belongs in the SDK docs as a performance note.
Cost: ~2 min. Probe: extend probes/ with `probe_gif_crc_cache.py`.

**Progress (2026-07-24):** CRC dedup confirmed — status=3 arrives from chunk 1
of a byte-identical multi-chunk re-upload (`probe_gif_crc_cache2.py`), so
early-exit is viable: a sender that stops on the first status=3 cuts an ~8.7s
re-upload to ~1.3s. Also caught an SDK misparse: GIF replies are StatusAck
family, and (1,0) had to join `_STATUS_ACK_KEYS` — the fourth misparse fixed in
this class (after timer/schedule/text). One caveat: single-chunk sends produced
a transient render glitch (stutter, CRT-like artifacts, bottom-row pixels stuck
orange-ish) once; attribution is pending `probe_gif_chunk1_isolation.py`, which
disambiguates playback-switch from glitch before any dedup fast path ships.

**Progress (2026-07-25):** `probe_gif_chunk1_isolation.py` ran. Recognition is
SINGLE-SLOT — chunk 1 of a *previously* stored gif (seed-7) returned status=1,
not 3, because a fresh seed-100 upload had displaced it; the device tracks only
the currently stored gif's CRC, not a library (multi-entry cache theory killed).
Lone unrecognized chunks (stored-but-displaced seed-7, never-seen seed-101) are
visually inert and safely abandoned — both reproduced clean, which narrows the
render-glitch suspect to the one unreproduced case: chunk 1 of the *currently*
stored gif (status=3, a possible messy playback-switch — one sample, not a
finding). Terminal-status semantics reopened: a cold seed-102 upload ended
terminal 3 where the prior night's cold seed-100 ended terminal 0, so the
"terminal 0 = fresh / 3 = duplicate" mapping is suspect. P2d
(`probe_gif_stored_chunk1.py`) is the closing probe: it fires the recognized
chunk 1 to catch the glitch, then samples three fresh-upload terminals
(seeds 103/104/105) for a distribution before any terminal-status claim.

**Progress (2026-07-25, P2d done):** `probe_gif_stored_chunk1.py` ran. Phase 1:
chunk 1 of the stored seed-102 gif returned status=3 at +1.10s and the panel
switched clock -> noise cleanly, no artifacts -- INSTANT PLAYBACK SWITCH
confirmed as a real primitive, and the transient render glitch did NOT reproduce
(downgraded to an unexplained one-off, kept on record). Phase 2 (three cold
uploads): seeds 103 and 105 ended terminal 3; seed 104 hit a mid-stream status=0
at the chunk-2 position, then kept acking 1 with NO terminal 3 -- a SILENT
FAILURE. Status model v2: GIF's vocabulary is the SAME as Timer/Schedule
(1=NEXT_CHUNK, 3=SAVED, 0=FAILED); the "terminal 0 = fresh store" reading was
wrong, and the 2026-07-24 0-endings were silent failures masked by
identical-looking noise fixtures (~1 in 4 observed). Remaining P2 question =
VISUAL confirmation of the silent-failure model with distinguishable fixtures:
P2e (`probe_gif_color_reliability.py`) uploads per-channel tinted gifs (RED/
GREEN/BLUE/YELLOW) so a doomed upload leaves the PREVIOUS color playing on the
panel, making silent failures directly observable.

## P3 — Graffiti byte-4 leftovers: ERASE hypothesis + values 5–7

On a NON-black background (push a dark-blue frame first — a black background
can't distinguish "erased" from "drew black"):
1. Draw a white block (b4=0), then send the SAME coords with b4=4: do the
   pixels turn black / restore background / nothing? (ERASE hypothesis; the
   one prior b4=4 test was on black and drew normally.)
2. b4=5, 6, 7 with a single off-center pixel each: accepted/nacked/what
   renders? (Mirror combos? The h/v mirror pair suggests 3 bits of options.)
   Cost: ~3 min. Extends the byte-4 map beyond 0/1/2.

## P4 — Streaming endurance: find the safe sustained rate

The flood benchmark killed the link twice; the render cap is ~1.75 fps. What
GlanceOS actually needs is the SAFE sustained envelope:
1. Unacked full frames paced at exactly 1.5 fps for 10 minutes — link alive?
   memory stable? notifies still ~1:1?
2. Graffiti delta ceiling: bursts of 255-px unacked commands — step the rate
   up (10/20/40/60 cmd/s × 30 s each) until the link degrades. The measured
   ceiling defines the animation budget for delta-driven scenes.
3. The GlanceOS mix: 1 full frame + N delta commands per second, 5 minutes.
Cost: ~25 min mostly unattended (panel shows a test pattern; operator can
leave). Directly feeds GlanceOS animated-scene design + an SDK streaming doc.

## P5 — Weekly Schedule verification via RTC spoofing

Same trick that mapped the Timer week bits in minutes. Schedule differs from
Timer: it DOES apply patch_week(), and the 2026-07-12 session left the end
boundary looking minute-exclusive but unproven, week-day mapping unverified,
PNG image-theme rendering unverified.
1. Spoof-day sweep of the patched week byte (fire/no-fire, 2 days ≈ full map).
2. Window boundaries: theme armed for [T, T+2min]; is the end minute
   inclusive or exclusive? What shows the second the window closes?
3. Image (PNG) theme content — renders? (GIF themes verified.)
Cost: ~15 min. Closes the last ⚠ subsystem short of PyPI.

## P6 — Multi-slot alarms (GlanceOS M7 Stage 4 groundwork)

Arm slots 0 and 1 for adjacent minutes (RTC-spoofed, DURATION_10S): both
fire? In order? What happens when a fire window overlaps another slot's
start? Does `timer_close` on slot 0 leave slot 1 armed? Do armed slots
survive a device power-cycle?
Cost: ~10 min. Defines the alarm UX GlanceOS can safely offer.

## P7 — Quick odds and ends (batch into any session's tail)

- **Power-state semantics**: after `turn_off`, do commands still ack? Does
  `turn_on` restore the prior mode or reset to clock? (Informs eco/night
  behavior in GlanceOS.)
- **Brightness floor**: app dial reads 0–100, our verified range is 5–100 —
  what do 1–4 do (nack? clamp? off)?
- **Countdown/chronograph shared state**: we saw a paused countdown hijack
  chronograph commands. One targeted sequence (arm countdown, pause, send
  chrono start/pause/etc.) to map the shared-state machine properly, since
  GlanceOS M7 uses daemon-rendered timers and must never trip over device
  state left by the vendor app.
- **Fullscreen-color persistence recheck** after tonight's resets (the
  3-day-persistence claim predates many firmware pokes).

---

*Maintainer additions below this line:*

## P8 — Canonical geometry, color-order, and flip contract

Prove the hardware contract behind `show_frame()` and `set_pixels()` rather
than relying on plausible-looking output. Send one full frame with unique RGB
swatches at all four corners, several asymmetric interior coordinates, and a
non-symmetric diagonal. Repeat it with screen flip enabled, then repeat the
same landmarks via graffiti.

Record:

1. Row-major vs. column-major mapping and the observed RGB channel order.
2. Whether full-frame and graffiti coordinates agree exactly.
3. Whether flip affects DIY frames, graffiti, native clock, and text equally.

Cost: ~5 min. Unblocks a documented geometry/orientation guarantee and catches
the most user-visible wrong-`ScreenSize` failure mode.

**DONE 2026-07-24** (probes/probe_p8_geometry.py, two runs): clean sweep —
row-major, top-left origin, RGB order; graffiti shares the frame coordinate
space exactly; flip is a 180° rotation applied at render to frames, graffiti,
and native modes alike (commands stay in canonical unflipped space).

## P9 — BLE packet-boundary and write-mode matrix

The transport deliberately re-splits protocol packets to the negotiated GATT
write size. Prove that BLE write boundaries do not change device behavior.
Send the same known-good payload while forcing write sizes 18/20, a medium size
(100–185), and 509/512 where the platform permits it. Cover one full DIY
frame, GIF, 32x32 text, and one Timer/Schedule upload if practical. For each,
compare write-with-response and write-without-response where supported.

Record rendered result, GATT errors, fa03 sequence, and wall time.

Cost: ~15 min. Directly validates transport re-splitting,
`write_size_override`, and the BlueZ low-MTU escape hatch; P4 measures rate,
while this probe proves correctness.

## P10 — Interrupted-upload recovery and saved-data integrity

Start from a known saved GIF/alarm/schedule asset. Deliberately interrupt a
larger replacement upload after (a) its first BLE packet, (b) its first outer
chunk, and (c) a middle outer chunk. Reconnect, inspect whether the old content
still works, then re-upload the same content successfully.

Record whether partial data becomes visible/corrupts storage, whether recovery
requires reset or DIY re-entry, and the fa03 handshake after retry.

Cost: ~15 min. Defines what `UploadError` means and whether automatic retry can
ever be safe. Publication-critical for native uploads.

**Progress (2026-07-24):** case (b) first-chunk-abandon is already covered at
the protocol level by `probe_gif_crc_cache3.py` phase 2 — chunk 1 of a
never-uploaded GIF returns status=1 (device waits for chunk 2), and a later full
upload was unaffected. So at minimum a first-chunk abandon does not corrupt
subsequent uploads; the render-glitch attribution and packet-level case (a) are
still open (`probe_gif_chunk1_isolation.py`).

## P11 — Persistence and reset matrix

Turn the existing P6/P7 persistence checks into one explicit matrix. For every
state below, test BLE disconnect/reconnect, software power off/on, and physical
power-cycle where practical:

- brightness, power, and flip;
- DIY frame, fullscreen color, GIF, text, clock, and effect;
- eco configuration;
- Timer/Schedule slots.

For each cell, record whether the state persists, resumes, resets to clock, or
requires a new command.

Cost: ~20 min. Supplies reliable reconnect documentation and tells the SDK when
it must invalidate DIY mode or restore caller-visible state.

## P12 — Command-order and display-mode state machine

Run deliberate transition sequences rather than testing modes in isolation:

1. DIY frame → text → full frame.
2. DIY frame → clock → graffiti → full frame.
3. GIF → effect → DIY frame.
4. Clock → countdown → chronograph → clock.
5. Power off → command → power on → full frame.

For every transition record fa03 acknowledgement, visual result, and whether
`invalidate_diy_mode()`/a DIY entry is necessary. Include the known paused
countdown/chronograph interaction from P7 as the time-mode branch.

Cost: ~10 min. Unblocks automatic mode invalidation in the client and prevents
callers from needing undocumented knowledge of device state.

## P13 — Non-destructive validation-boundary sweep

Exercise safe boundary values, recording both SDK validation and device ack/
visual behavior. Do not fuzz blindly and keep password/OTA exclusions intact.

- brightness: 0, 1, 4, 5, 100, 101, 255;
- RGB channels: 0, 1, 254, 255;
- countdown: 00:00, 00:59, 59:59, 60:00;
- scoreboard: -1, 0, 999, 1000;
- effect style/count boundaries;
- eco time boundaries;
- graffiti batch lengths 0, 1, 255, 256.

Cost: ~10 min. Aligns SDK validation with actual firmware behavior and guards
against accidental, permanent API semantics.

## P14 — Ack timing, duplication, and silence characterization

For representative config commands, graffiti, frames, text, and chunked uploads,
timestamp GATT write completion and each fa03 notification. Measure whether
acks arrive before/after write completion, duplicate frequency, missing-ack
frequency, and behavior after reconnect.

Cost: ~10 min. Supports defensible default timeouts and identifies which command
families must remain fire-and-forget.

## P15 — Long soak with intentional recoveries

Extend P4 from throughput to resilience: run 12–24 h at a conservative mixed
workload, periodically switch native/DIY modes, and intentionally exercise a
Bluetooth toggle or device power-cycle. On Windows, include host sleep/resume.

Sample process memory, reconnect count, listener count, and last failure.
Acceptance: no unbounded growth, duplicate callbacks, stuck reconnect task, or
connected-but-invisible state; the next full frame reliably heals the panel.

Cost: mostly unattended. This is the highest-confidence evidence for the
transport/reconnect promise made by a public SDK.

## P16 — Community multi-model compatibility pack

Create a non-destructive, contributor-runnable probe that emits a redacted JSON
report plus optional photos/video. Capture advertised name, dimensions, GATT
service/characteristic properties, reported write size, geometry/color/flip
result, text behavior, DIY/GIF/graffiti outcome, and acknowledgement behavior.

Prioritize 16x16 and 64x64 panels: the SDK exposes those sizes but current
hardware evidence is concentrated on the reference 32x32.

Cost: SDK engineering plus community panel time. This is more valuable for a
PyPI release than another obscure opcode, because it turns one-panel truth into
a scalable compatibility table.

## P17 — Brightness and eco interaction matrix

While DIY, GIF, effect, and clock are active, change brightness and observe
whether it applies immediately. Then enter/exit eco and test whether it restores
the previous brightness, survives reconnect/power-cycle, or interacts with
screen power state.

Cost: ~10 min. Brightness is a universal user-facing feature; its cross-mode
semantics should be documented rather than inferred.

## P18 — Add recovery and lifecycle actions to the P1 HCI capture

During the planned app capture also record: reconnect after intentional app
disconnect, Bluetooth toggle/resume, explicit DIY enter → frame → exit, repeated
identical GIF upload, and any alarm/schedule disable action offered by the app.

Cost: negligible once P1 is running. Broadens the capture from command-byte
discovery into initialization, persistence, transfer, and recovery evidence.






For every probe, standardize the recorded evidence:

SDK commit:
Panel advertised name:
Panel dimensions:
Host OS / BLE backend:
Reported write size:
Write mode:
Command/payload digest:
fa03 notifications, with timestamps:
Visual result:
Persistence result:
Conclusion / capability-table update:
