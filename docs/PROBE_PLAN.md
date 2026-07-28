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

## P1 — HCI snoop session: the app's actual bytes  ✅ CAPTURED + PARSED 2026-07-25

**Done.** The capture was taken against our 32×32 panel, decoded with the
bundled `pyidotmatrix-btsnoop` CLI (`pyidotmatrix/btsnoop.py`), and every
finding below is now in `capabilities.py` and the builders.

**What it settled.** The effect speed mystery has an answer: the app **never
sends `common.set_speed`** — not once, speed dial included — so that command is
dead code in the vendor ecosystem. Effect speed is byte 5 of the standard effect
command, and the dial re-sends the *whole* command on gesture release
(`[1c 00 03 02 style speed count + count*RGB]`, style 0, 7 colors, speed 0x5a
then 0x64, acked `[05 00 03 02 01]`). The music screen turned out to be
phone-side: the app streams `[21 00 01 02 00]` + 16 level bytes to fa02 at
~10 Hz, unacked, levels observed 0x00–0x0d, 8 bands mirrored into a palindrome —
now `build_rhythm_levels`. Three of our frames were wrong and are fixed:
`set_mic_type` is 6 bytes (`[06 00 0b 80 01 64]`, we sent 5), the GIF header's
`time_sign` is little-endian with the app's default key emitting 5 (we wrote
big-endian 10), and the text path has a second glyph cell — 8×16, 16 bytes per
glyph, separator tag **0x02**, falsifying our "64 → tag 5, else tag 6" note. Our
16-byte text header and metadata byte 2 = 1 were confirmed byte-exact, as were
the eco/power frames, the brightness dial (our frame at ~12 ms spacing; ~17%
nacks under load are load-shedding the app ignores), and the clock flags
(0x80 = show_date, 0x40 = hour24, low 3 bits = style). Smaller finds: the DIY
frame path accepts an RGBA **PNG** payload under our exact 9-byte header
(acked `[05 00 00 00 01]`); the paint eraser is just `#000000` with `move=0`,
and only single-pixel 10-byte commands ever appeared; **the vendor app's own**
connect handshake is merely CCCD subscribe + `set_time` + clock style -- this
is the app's behavior, observed only in the app's own traffic; our
`IDotMatrixClient.connect()` sends none of it (see `color.show` in
capabilities.py for the 2026-07-27 correction of a claim that conflated the
two). A device ID string
`"TR2306R007-15"` is readable at ATT handle 0x0007; and `set_time` drew a
9-byte reply `[09 00 01 80 04 0f 01 03 00]` that `parse_response` ignores
(len == 5 requirement deliberately unchanged).

**Not settled by the capture:** it contained **no true duplicate GIF upload**,
so the dedup / single-slot-CRC evidence from P2 remains ours alone — P18 still
has a job.

### P1-follow-up (a) — effect byte-5 retest with the captured frame  ✅ DONE 2026-07-25

Replayed the byte-identical captured effect command at speed 100 / 5 / 100
(style 0, the same 7 colors, `[1c 00 03 02 00 SPEED 07]`), each a complete
command as the app re-sends it — `probes/probe_p1_followups.py` group A.

**PASSED: effect speed control works.** Smooth → visibly slow → smooth again,
each send acked `[05 00 03 02 01]`. `effect.speed` moves **KNOWN_BROKEN →
VERIFIED**. The old probe methodology, not the byte, was the bug — and the
prime suspect within that methodology is our builder's malformed length byte
(`6 + colorCount` = 13 where the app sends `0x1c` = 28 = the true total frame
length), now fixed in `protocol/effect.py`. Not yet isolated → P1-(c).

### P1-follow-up (b) — live test of the rhythm-levels stream  ✅ DONE 2026-07-25

Streamed `[21 00 01 02 00]` + 16 mirrored level bytes at a measured 10.0 Hz,
120 frames per phase, bare and then after the corrected 6-byte mic-type frame —
`probes/probe_p1_followups.py` group B.

**PASSED: the stream renders.** Cold from the clock, with no mode entry at all:
"music mode appeared but choppy". The mic-type frame `[06 00 0b 80 01 64]`
acked **positive** (type=11 sub=128 accepted) and the identical stream then drew
a *different* animation — "both have separate animation" — so it selects a
visualization rather than gating the stream. A static all-`0x0d` frame rendered
too. `music_sync.rhythm_levels` and `music_sync.set_mic_type` both move
**SOURCE_DERIVED → VERIFIED** — set_mic_type's verification covers the corrected
six-byte frame only, since mic_type 1 is the sole value ever sent and what the
others select is unobserved. `send_image_rhythm` stays KNOWN_BROKEN, now with a
working replacement.

*Footnote from the session:* a phantom animation appeared after the probe
disconnected, attributed (unconfirmed) to the operator's phone app
auto-reconnecting once we released the link.

### P1-(c) — effect length-byte isolation A/B  ✅ CLOSED 2026-07-26 (result superseded by the speed sweep)

`probes/probe_effect_length_byte.py`. Follow-up (a) proved byte 5 works but
changed several things at once versus the 2026-07-21 probes. This one changes
**exactly one byte**: two hand-built frames identical in every position except
byte 0 — the old malformed `0x0d` and the correct `0x1c` — sent at SPEED=5 and
SPEED=100 in four phases (old@100, old@5, correct@100, correct@5) via
`client.effect._send(..., verify=False)`, deliberately bypassing the now-fixed
builder.

*Reads out:* if **old@5 does not slow** while correct@5 does, the length byte
was the culprit and the whole 2026-07-21 "speed is inert" record is explained.
If old@5 *does* slow, the length byte was never the issue and the difference
lies in style/palette or the mid-animation delivery those probes used — which
would reopen the question of what made them inert.

Cost: ~5 min. Closes the last loose end on `effect.speed`'s history and gives
`effect.show_chunked` its retest rationale.

### P1-(d) — music-sync per-band pixel mapping  (open)

Follow-up (b) proved the stream renders but left the mapping unread: how the 16
level bytes become pixels (columns? rows? how many? what does "full" reach?),
and whether the two visualizations map them differently. Needs single-band
frames walked across all 16 positions, held long enough to photograph, in both
visualization modes. *Target: promote `music_sync.rhythm_levels` from "renders"
to "understood", which is what a usable spectrum API needs.*

Cost: ~15 min.

<details>
<summary>Original P1 plan (kept for method reference)</summary>

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

</details>

## P2 — GIF CRC cache (overclocked's claim)  ⚠ PARTIAL 2026-07-25

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

**P2 CLOSED (2026-07-25):** `probe_gif_color_reliability.py` ran the four tinted
cold uploads (RED/GREEN/BLUE/YELLOW). The panel matched every ack terminal: RED
and BLUE hit a mid-stream status=0 at the chunk-2 position (+1.6-1.7s) with no
terminal 3 and NEVER PLAYED (the prior color stayed up -- a silent failure,
seen); GREEN and YELLOW ended terminal 3 (+8.9s) and PLAYED. The silent-failure
model is now VISUALLY PROVEN, and the CHUNK-2 RACE is identified: every failure
ever observed (seed 104, RED, BLUE) died at the chunk-2 position, our blind
sender firing chunk 2 before the device finished digesting chunk 1's header
(~50% failure this session). The SDK rewrite committed alongside this result is
the remedy -- `client.py`'s `_send_gif_upload` paces on the StatusAck handshake
(send a chunk, await its ack, restart the whole upload once on a doomed/timed-out
pass), the vendor app's own approach. The instant-switch primitive from P2d is
exposed as `gif.activate_stored()`: one recognized chunk 1 switches playback in
~1s. No further P2 GIF probes planned.

## P3 — Graffiti byte-4 leftovers: ERASE hypothesis + values 5–7  ✅ CLOSED 2026-07-25

On a NON-black background (push a dark-blue frame first — a black background
can't distinguish "erased" from "drew black"):
1. Draw a white block (b4=0), then send the SAME coords with b4=4: do the
   pixels turn black / restore background / nothing? (ERASE hypothesis; the
   one prior b4=4 test was on black and drew normally.)
2. b4=5, 6, 7 with a single off-center pixel each: accepted/nacked/what
   renders? (Mirror combos? The h/v mirror pair suggests 3 bits of options.)
   Cost: ~3 min. Extends the byte-4 map beyond 0/1/2.

**P3 CLOSED (2026-07-25):** `probe_graffiti_byte4_erase.py` ran on a dark-blue
field. The byte-4 map is COMPLETE: only 1 (HORIZONTAL_MIRROR) and 2
(VERTICAL_MIRROR) carry firmware semantics; 0 and 3-7 all draw PLAIN. The ERASE
hypothesis for byte4=4 is FALSIFIED -- white pixels re-sent with b4=4 stayed
white (they neither went black nor restored the background), with the honest
same-color-resend caveat that "plain draw" and "no-op" are indistinguishable in
that one phase but plain-draw is parsimonious given the 2026-07-21 black-field
draw and the 5/6/7 results. b4=5/6/7 each rendered a single pixel at its own
coords with no mirrored copies and no nack; graffiti stayed ack-silent
throughout. Conclusion: the APK's DiyImageMoveType enum names (OVERALL_MOVEMENT,
ERASE) describe APP-SIDE paint-tool behavior, not firmware behavior. No further
byte-4 probes planned.

## P4 — Streaming endurance: find the safe sustained rate  ✅ CLOSED 2026-07-28

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

**RAN 2026-07-28** — `probes/probe_p4_streaming_endurance.py`, all three
phases. **All three sub-items are answered.** Zero reconnects anywhere.

    step                          ran  frames  deltas   acks  ack:F  sent/s  target  miss
    full frames 1.5 fps        600.0s     900       0    900   1.00    1.50    1.50     0
    deltas 10 cmd/s             30.0s       0     300      0      -   10.00   10.00     0
    deltas 20 cmd/s             30.0s       0     600      0      -   19.99   20.00     0
    deltas 40 cmd/s             30.0s       0    1200      0      -   39.98   40.00     0
    deltas 60 cmd/s             30.0s       0    1657      0      -   55.23   60.00   143
    mix 1 fps + 10 cmd/s       300.0s     300    2999    218   0.73   11.00   11.00     1

1. **1.5 fps full frames are comfortably sustainable.** Ten minutes, perfect
   1:1 frame-to-ack correspondence, exact pacing, no back-pressure and no
   decay — the safe sustained envelope sits just under the ~1.75 fps render cap.
2. **The graffiti delta ceiling is ~40 cmd/s clean.** 10/20/40 all exact with
   zero missed slots; 60 cmd/s achieved only 55.23/s and dropped 143 slots.
   Consistent with the ~20 ms per graffiti command already measured (~50/s
   theoretical). Design against 40 cmd/s; ~55/s is the hard ceiling.
3. **⚠ Mixing deltas into a full-frame stream costs ~27% of the frame acks.**
   Frames alone: ack:F 1.00. Mixed: **0.73** over five minutes, corroborated by
   0.87 in the 15 s smoke run. The fa03 ack is the device's frame-processed
   signal and the SDK's free flow control, so mixed-mode streaming degrades
   flow control by roughly a quarter — a delta-stream-plus-keyframe design that
   paces on frame acks gets materially fewer of them than pure full-frame mode.
   **Mechanism unknown**; the measurement and its consequence are recorded, no
   more. Promoted to `display.show_frame` / `display.set_pixels` in
   capabilities.py and to Protocol Notes § Streaming & performance.

**Two blind spots in the probe itself**, recorded in its docstring so the
numbers are not over-trusted: cleanup is **not instrumented** (the `deltas` and
`mix` phases each ended with the cleanup clock write failing `Unreachable` and
forcing a reconnect, none of which reaches the summary), and ACK_COLLAPSE's
floor is **0.50**, so the mix phase's 0.73 never flagged. Likewise 55.23/60 =
0.92 sits above the 0.75 RATE_COLLAPSE trigger, so 143 missed slots scored
"clean". Those cleanup failures are **unexplained, not a defect** — P4b tested
the graffiti-breaks-the-next-write hypothesis and did not reproduce it (see
`probes/probe_p4b_post_stream_write.py`).

Degradation is defined in code, not judged: WRITE_FAILED (a write raised),
LINK_DOWN (reconnect_count rose, a reconnect event fired, or is_connected went
False), ACK_COLLAPSE (acks per full frame below 0.50 — full-frame steps only,
since graffiti is ack-silent by design), RATE_COLLAPSE (achieved send rate below
0.75 of target). Ratio criteria are not judged during a step's first 10 s, since
acks lag sends by up to ~4.3 s (P14). The FIRST criterion to trip ends the step
and abandons the rest of the phase — no escalation into another link death.
Deltas go through `display.set_pixels` (the call GlanceOS's pipeline makes) at
exactly 255 coordinates per command, the hard safety limit from P13 phase E.

    python probes/probe_p4_streaming_endurance.py frames   # sub-item 1, ~10.5 min
    python probes/probe_p4_streaming_endurance.py deltas   # sub-item 2, ~2.5 min max
    python probes/probe_p4_streaming_endurance.py mix      # sub-item 3, ~5.5 min
    python probes/probe_p4_streaming_endurance.py smoke    # harness shakedown, ~1 min

## P5 — Weekly Schedule verification via RTC spoofing  ✅ CLOSED 2026-07-27

Same trick that mapped the Timer week bits in minutes. Schedule differs from
Timer: it DOES apply patch_week(), and the 2026-07-12 session left the end
boundary looking minute-exclusive but unproven, week-day mapping unverified,
PNG image-theme rendering unverified.
1. Spoof-day sweep of the patched week byte (fire/no-fire, 2 days ≈ full map).
2. Window boundaries: theme armed for [T, T+2min]; is the end minute
   inclusive or exclusive? What shows the second the window closes?
3. Image (PNG) theme content — renders? (GIF themes verified.)
Cost: ~15 min. Closes the last ⚠ subsystem short of PyPI.

**Progress (2026-07-27):** `probes/probe_p5_schedule.py` ran. Day-bit map
CLOSED: a theme armed for Wednesday's bit fired when the device RTC was
spoofed to Wednesday and stayed silent when spoofed to the non-adjacent
Saturday with nothing re-armed -- the source-traced patch_week() encoding is
now hardware-confirmed (the first such confirmation, since Timer's own
week-bit map does not call patch() and never covered this path). PNG
(CONTENT_IMAGE) theme rendering CLOSED: a static PNG theme rendered inside
its window. STILL OPEN: the window end-boundary question (inclusive vs.
exclusive minute) did not reach a clean read -- the continuous, unlabelled
multi-minute watch this phase depends on proved fragile to interrupt-free
observation in practice. **Follow-up queued:** a redesigned P5 boundary
probe that labels the boundary crossing itself (e.g. a scoreboard tick or a
distinct visual marker at the moment the RTC crosses the window's end
minute) rather than relying on one long silent watch.

**CLOSED (2026-07-27, P5b):** `probes/probe_p5b_window_boundary.py` ran the
redesigned control/test pair and answered the boundary question. Schedule is
evaluated on MINUTE TICKS, not continuously: jumping the RTC directly into
the middle of the armed window fired nothing until the device's own clock
naturally rolled over to the next minute. THE END MINUTE IS INCLUSIVE -- a
[12:10, 12:12] window covers 12:10, 12:11 and 12:12, closed by 12:13. This
OVERTURNS the 2026-07-12 "ended a minute early" / minute-exclusive reading,
which was an artifact of the same minute-tick evaluation, not a real
exclusive boundary. No further P5 probes planned; see capabilities.py's
experimental.schedule_set_theme entry for the full account.

## P6 — Multi-slot alarms (GlanceOS M7 Stage 4 groundwork)  ✅ CLOSED 2026-07-27

Arm slots 0 and 1 for adjacent minutes (RTC-spoofed, DURATION_10S): both
fire? In order? What happens when a fire window overlaps another slot's
start? Does `timer_close` on slot 0 leave slot 1 armed? Do armed slots
survive a device power-cycle?
Cost: ~10 min. Defines the alarm UX GlanceOS can safely offer.

**CLOSED (2026-07-27):** `probes/probe_p6_alarms.py` ran the default Q1-Q3
sequence, an isolated `q3` mode, the `arm`/`check` physical power-cycle pair,
and two added collision modes (`collide-colour`, `collide-order`). Q1:
two independently armed slots BOTH fire, in order, with per-slot buzzer
(slot 0 red+beep, slot 1 blue silent). Q3: `timer_close` is a PARTIAL
disarm -- it clears the closed slot's content but leaves its schedule and
buzzer armed (reproduced twice in isolation), which HALF-RETRACTS the old
"does not disarm" reading rather than confirming or fully overturning it.
Q4: alarms are FLASH-PERSISTENT -- both slots and their payloads survived a
physical power-cycle. New beyond the original four questions: when two
slots collide on the same minute, the HIGHER SLOT INDEX always wins the
display (four index x order x colour combinations, same winner every time);
both buzzers still sound, and the loser's content is never displayed rather
than overwritten. The state-echo status vocabulary is also corrected: this
run's close-acks read 3 (had content) and 0 (empty/consumed), not the
"3 / 1" pairing the probe's own comments and the 2026-07-12 session assumed
-- that status-1 reading has not been reproduced. Q2 (the original
60s-vs-10s overlapping-window question) was exercised in the default
sequence, but no attributed readout survived into this documentation pass;
do not cite an outcome for it from this run. Full account in capabilities.py's
experimental.timer_close and experimental.timer_set entries.

## P7 — Quick odds and ends (batch into any session's tail)  ✅ CLOSED 2026-07-27

- **Power-state semantics**: after `turn_off`, do commands still ack? Does
  `turn_on` restore the prior mode or reset to clock? (Informs eco/night
  behavior in GlanceOS.)
- ~~**Brightness floor**: app dial reads 0–100, our verified range is 5–100 —
  what do 1–4 do (nack? clamp? off)?~~ **CLOSED by P13** (probes/
  probe_boundary_sweep.py, 2026-07-25): raw frames at 0/1/4/101/255 all NACK
  with `05 00 04 80 00`, no clamping, firmware range exactly 5-100.
- **Countdown/chronograph shared state**: we saw a paused countdown hijack
  chronograph commands. One targeted sequence (arm countdown, pause, send
  chrono start/pause/etc.) to map the shared-state machine properly, since
  GlanceOS M7 uses daemon-rendered timers and must never trip over device
  state left by the vendor app.
- **Fullscreen-color persistence recheck** after tonight's resets (the
  3-day-persistence claim predates many firmware pokes).

**Progress (2026-07-27):** `probes/probe_p7_odds_and_ends.py` ran.
Power-state semantics CLOSED: commands sent to a powered-off panel are still
accepted and execute invisibly into an unseen framebuffer; `turn_on` reveals
that resulting framebuffer rather than restoring the prior mode or resetting
to the clock (capabilities.py's common.set_power entry). The countdown/
chronograph shared-state mapping (phases 3-8) was exercised but a verified
per-step readout was not carried forward into this documentation pass; treat
it as still needing a citation-worthy result beyond the existing 2026-07-20
caveats in capabilities.py's chronograph.set_mode entry. **Phase 9 (fullscreen-
colour persistence) IS recorded, corrected 2026-07-27:** an earlier pass this
same day wrongly voided phase 9's result on the theory that our own reconnect
repaints the clock via a handshake seen in the P1 HCI capture -- that
handshake is the vendor app's, observed only in the app's traffic; our
`IDotMatrixClient.connect()` sends no such thing (verified against
`client.py`/`transport/ble.py`). Phase 9's observation stands: magenta set,
12s disconnect/reconnect, panel showed the clock, nothing we sent explains it.
**Phase 9 is now RESOLVED (2026-07-27), and it is the earliest instance on
record of LAZY DISPLAY-STATE PERSISTENCE.** This caveat read two wrong ways
before that: first as a "reset shadow" (phase 9 runs immediately after that
probe's own `common.reset()` cleanup), then as an open choice between genuine
device-side colour volatility and a "first-connection shadow" -- a model since
**retracted**, see P11 below. The reset is not the variable (`--no-reset` died
identically). The colour-volatility branch is dead too: `--no-reset color` is
phase 9's scenario reproduced under control -- fullscreen colour written and
then disconnected from ~8 s later with no prior reconnect -- and it died the
same way, while the persistence matrix's colour row, armed with a prior
reconnect behind it, held across the identical interruption. Colour is durable
once it has dwelt, or once the session has already reconnected. The phase-9
retest that used to be queued below is **cancelled**; see capabilities.py's
color.show and display.persistence_matrix entries.

---

*Maintainer additions below this line:*

## P8 — Canonical geometry, color-order, and flip contract  ✅ CLOSED 2026-07-24

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

## P9 — BLE packet-boundary and write-mode matrix  ✅ CLOSED 2026-07-27

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

**CLOSED (2026-07-27):** `probes/probe_p9_write_boundaries.py` ran, including
a re-observation of the 514-byte block and the write-mode pair after an
initial partial pass. Packet re-splitting renders correctly at every write
size tested -- 18, 20, 128, and the link's negotiated 514 bytes -- across all
three payload types (DIY frame, GIF, 32x32 text); the BlueZ low-MTU escape
hatch is safe to recommend. Unacknowledged (no-response) writes ran 3-6x
faster than response-acked writes with no rendering difference. No further
P9 probes planned.

## P10 — Interrupted-upload recovery and saved-data integrity  ✅ CLOSED 2026-07-27

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

**CLOSED (2026-07-27):** `probes/probe_p10_interrupted_upload.py` ran all
three interruption cases. `activate_stored(BASE)` returned SAVED after every
case -- interrupted uploads do NOT touch previously stored content, so
`UploadError` means only "the new content did not arrive" and the automatic
whole-upload retry in `_send_gif_upload` is safe to run unattended. Also
recorded: a GIF already playing freezes the instant a new upload starts
arriving, and `gif.activate_stored()` restarts playback at frame 0 rather
than resuming. The closing DIY health-check frame rendered in every case, so
interrupted native uploads do not poison the frame pipeline. The
2026-07-24 render-glitch attribution referenced above remains a separate,
still-unreproduced item (see capabilities.py's display.visual_transients
entry).

## P11 — Persistence and reset matrix  ⚠ PARTIAL 2026-07-27 (BLE-reconnect column closed; software-power-cycle column has one void cell)

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

**PARTIAL (2026-07-27):** `probes/probe_p11_persistence.py` ran both automated
columns -- BLE disconnect/reconnect (~6s), then software power off/on (~5s)
chained onto whatever the first interruption left in force -- across every
row (clock, DIY frame, fullscreen colour, GIF, text, effect, flip, brightness,
eco, power). The DIY frame resets to the clock on the BLE-reconnect column;
every native mode held there. **Read every cell as a PROTECTED result:** the
sweep arms its rows in sequence, so from the second row onwards each state was
established after an earlier disconnect/reconnect in the same process --
condition (B) of the model described below -- so "GIF held" here and "GIF died"
there are both true and describe different conditions. The clock control row is
additionally vacuous as a durability test, since a clock face dying back to the
clock face is undetectable. **CORRECTION, methodology flaw:** the DIY row's
software-power-cycle CELL IS VOID, not a second confirmation of volatility --
the probe establishes each row's state once and does not re-arm it between
the two interruptions, so for DIY (the only row that already lost the first
interruption) the second interruption only re-observed the clock the first
one had already produced. Every other row's chained result is still valid,
since their state survived interruption 1 and was genuinely there to be
power-cycled. Do not trust the DIY x software-power-cycle cell until it is
re-run with the state re-armed in between (queued below). Cross-validates
brightness's "persists until the next command" and eco's "autonomous device
state". CORRECTED cross-reference to P12 (see docs/PROBE_PLAN.md's P12
section and capabilities.py's display.invalidate_diy_mode): "DIY re-entry is
required after a software power off/on" is WRONG as a blanket rule -- a clean
P12 sequence-5 rerun with nothing sent while the panel was dark found the DIY
frame survived the power cycle with no re-entry needed. The earlier
green-only result traced to an invisible scoreboard command sent while the
screen was dark, which left a native mode live at power-on; re-entry tracks
whether a native mode is actively live, not the power cycle itself. GlanceOS
consequence: after a BLE reconnect the panel shows the clock and the caller
must re-push a frame -- no native mode covers for it; whether a bare software
power cycle carries the same consequence for DIY is unresolved pending the
void cell's re-run. A reproducible display-durability effect surfaced in the
same run and was chased over two evenings. It was named twice and wrongly both
times -- first a "reset shadow" blamed on `common.reset()`, then a
"first-connection shadow" scoped to the client session. **Both names are
retracted.** What it actually is: **LAZY DISPLAY-STATE PERSISTENCE**, a panel
property already recorded in this lab on 2026-07-12 ("the device persists its
current native mode to flash LAZILY, dwell somewhere under ~3 min, and boots
into the last persisted mode") and 2026-07-17 ("clean BLE disconnect → device
exits DIY → reverts to the persisted screen in ~2s"), **plus one separate,
unexplained prior-reconnect effect**. Display content renders and acks SAVED,
but a clean disconnect reverts the panel to the last *persisted* mode, so
content written and disconnected from too quickly is lost. It survives if
**either** condition holds: **(A) DWELL** -- the ladder brackets the threshold
at 100 s < t <= 180 s (8/30/60/75/90/100 all died, 180 survived), matching this
lab's 2026-07-12 "under ~3 min" record; or **(B) a prior disconnect/reconnect
earlier in the same session** -- `--preamble ble gif` survives at ~8 s where the
matched `--no-reset gif` control dies, reproduced twice, and extended to
fullscreen colour by G7. **(B)'s mechanism is now known (G8): a prior reconnect
ARMS THE FLASH COMMIT** -- a colour written 8 s after a reconnect booted back
after a physical power cycle, so (A) unassisted is a lazy commit at 100-180 s
while (B) commits in <=8 s.
`common.reset()` is NOT involved (`--no-reset` died twice), a same-connection
power blink does NOT help (`--preamble power` died), and it is not GIF-specific
(`--no-reset color` died with no payload in play). Note also that a dying run
yields exactly ONE measurement: once the reconnect has killed the content, the
second interruption only re-reads a clock that was already up. See
capabilities.py's display.persistence_matrix entry for the full evidence table,
the config-class / display-class model, the pointer-not-payload result, and the
retraction of the per-client-session claim; P19 below carries the open
questions.
**STILL OPEN:**
the PHYSICAL power-cycle column (pulling mains power at the wall) has not
been run for this matrix's rows -- P6's Q4 physical power-cycle covered Timer
alarms only, not this matrix. Timer/Schedule slots also remain out of scope
for this probe by design (see
its docstring's NOT COVERED note -- those live in the `experimental`
namespace). See P19 below for the queued physical-column follow-up.

## P12 — Command-order and display-mode state machine  ✅ CLOSED 2026-07-27

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

**CLOSED (2026-07-27):** `probes/probe_p12_mode_state_machine.py` was rebuilt
one-sequence-per-invocation (the original multi-sequence version produced an
unfollowable run twice) and all five sequences ran, each with an attributed
operator readout. Full result in the probe's own RESULT block and in
capabilities.py's display.invalidate_diy_mode entry. HEADLINE: the real
question is not "does DIY mode need re-entry", it is "is a native mode still
actively drawing" -- a naive frame is never rejected or silently swallowed at
the protocol level, it renders, and what happens next depends on whether
something else still owns the framebuffer. Re-entry required after TEXT (lost
a repaint race, not swallowed), GIF+EFFECT (the effect operates on the live
framebuffer and dragged the injected frame into its own animation), and the
TIMER BRANCH (native modes repaint only their own dirty regions). No re-entry
needed after CLOCK+GRAFFITI or after a clean POWER OFF/ON. Sequence 2's own
separate result: graffiti sent onto a running native clock does NOT composite
over it, it forces a mode switch -- the daemon's delta-path assumption is
only safe once the panel is already in the pixel/DIY framebuffer. Sequence
5's result corrects the earlier "DIY re-entry is required after power
off/on" reading (see capabilities.py's display.persistence_matrix): that
result traced to an invisible scoreboard command sent while the screen was
dark, not to the power cycle itself.

## P13 — Non-destructive validation-boundary sweep  ✅ CLOSED 2026-07-25

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

**P13 CLOSED (2026-07-25):** `probes/probe_boundary_sweep.py` drove the real
firmware limits by hand-building RAW frames, since the SDK's own validation is
stricter than the wire and would otherwise hide them. Findings were recorded
into `capabilities.py` on 2026-07-28 — the probe had deferred recording to avoid
an edit collision and it was then forgotten for three days, which is the drift
this plan's status markers now exist to prevent.

1. **Brightness: the firmware range is EXACTLY 5–100, rejected not clamped.**
   Raw frames at 0, 1, 4, 101, 255 ALL nacked (`05 00 04 80 00`) and the panel
   never changed brightness. The SDK's own 5–100 validation matches firmware
   precisely. **This also closes P7's "brightness floor" question** (struck
   through in that section): 1–4 nack, the device does not clamp and does not
   turn the panel off.
2. **Fullscreen colour: every extreme is ACCEPTED — there is no rejected RGB
   value** — but the ends are not visually distinct. `(1,1,1)` renders as BLACK
   (below the LEDs' turn-on threshold, indistinguishable from a dark panel, so
   it is useless as a "barely lit" signal); `(254,254,254)` is indistinguishable
   from full white; `(0,0,0)` is a plain black raster, NOT a powered-off panel —
   `common.set_power(False)` remains the only real off.
3. **Countdown out-of-range minutes are ACCEPTED-THEN-ABORTED.** A raw
   `[7,0,8,128,1,60,0]` (60:00) was not nacked: the device accepted it and then
   killed the countdown that was already running, falling back to the clock.
   Neither clamped to 59:59 nor rejected — so the builder's `minutes<=59` check
   is load-bearing, not cosmetic.
4. **Scoreboard out-of-range scores are SILENTLY IGNORED.** A raw
   `[8,0,10,128,232,3,0,0]` (1000, LE `0x03E8`) produced NO ACK AT ALL and the
   panel kept showing the previous 999 — no nack, no 16-bit wrap. The builder's
   999 clamp is the only thing keeping this from being an invisible no-op.
5. **⚠️ 256 PIXELS IN ONE GRAFFITI COMMAND KILLS THE DEVICE — the
   highest-severity hazard on record.** One coordinate over
   `graffiti.MAX_PIXELS_PER_COMMAND=255` (size header `(8,2)` = 520 bytes): the
   GATT write failed mid-transfer, the panel STOPPED ADVERTISING entirely,
   reconnect raised `BleakDeviceNotFoundError`, the display went black, and a
   **PHYSICAL POWER CYCLE** was required — the probe's own cleanup could not
   run. There is no nack and nothing to catch. The 255 cap is a hard safety
   limit, not a tuning constant. **The public API is safe** (`client.py`'s
   `GraffitiFeature.set_pixels` and `display/ble_display.py`'s `set_pixels` both
   batch before building); the hazard is reachable only from hand-built raw
   commands — which is exactly what probe scripts do, so any future probe author
   touching graffiti must respect the cap.

## P14 — Ack timing, duplication, and silence characterization  ✅ CLOSED 2026-07-27

For representative config commands, graffiti, frames, text, and chunked uploads,
timestamp GATT write completion and each fa03 notification. Measure whether
acks arrive before/after write completion, duplicate frequency, missing-ack
frequency, and behavior after reconnect.

Cost: ~10 min. Supports defensible default timeouts and identifies which command
families must remain fire-and-forget.

**CLOSED (2026-07-27):** `probes/probe_p14_ack_timing.py` ran seven command
families at 5 repeats each. No family was silent -- every family acked on
every repeat. First-ack latency clustered by shape: flat config/native-mode
commands (brightness, scoreboard, clock) replied in ~0.13-0.30s; full-frame
commands (the DIY frame, the effect command) replied in ~0.6-0.9s.
`transport.await_device_ack`'s 2.0s default has margin over every family
measured. This run is also the evidentiary basis for retracting the
"0x0d effect frames never ack" finding from `probe_effect_length_byte2.py`
(2026-07-26) -- that silence was an instrumentation bug (reading the ack
list before the device's reply had arrived), not a device behavior. See
capabilities.py's new common.ack_timing entry.

## P15 — Long soak with intentional recoveries  ⬜ OPEN

Extend P4 from throughput to resilience: run 12–24 h at a conservative mixed
workload, periodically switch native/DIY modes, and intentionally exercise a
Bluetooth toggle or device power-cycle. On Windows, include host sleep/resume.

Sample process memory, reconnect count, listener count, and last failure.
Acceptance: no unbounded growth, duplicate callbacks, stuck reconnect task, or
connected-but-invisible state; the next full frame reliably heals the panel.

Cost: mostly unattended. This is the highest-confidence evidence for the
transport/reconnect promise made by a public SDK.

## P16 — Community multi-model compatibility pack  ⬜ OPEN (needs contributors' panels)

Create a non-destructive, contributor-runnable probe that emits a redacted JSON
report plus optional photos/video. Capture advertised name, dimensions, GATT
service/characteristic properties, reported write size, geometry/color/flip
result, text behavior, DIY/GIF/graffiti outcome, and acknowledgement behavior.

Prioritize 16x16 and 64x64 panels: the SDK exposes those sizes but current
hardware evidence is concentrated on the reference 32x32.

Cost: SDK engineering plus community panel time. This is more valuable for a
PyPI release than another obscure opcode, because it turns one-panel truth into
a scalable compatibility table.

## P17 — Brightness and eco interaction matrix  ✅ CLOSED 2026-07-27

While DIY, GIF, effect, and clock are active, change brightness and observe
whether it applies immediately. Then enter/exit eco and test whether it restores
the previous brightness, survives reconnect/power-cycle, or interacts with
screen power state.

Cost: ~10 min. Brightness is a universal user-facing feature; its cross-mode
semantics should be documented rather than inferred.

**CLOSED (2026-07-27):** `probes/probe_p17_brightness_eco.py` and
`probes/probe_p17b_eco_isolation.py` (lux-instrumented) both ran. Brightness
applies IMMEDIATELY and PERSISTS in every mode tested (DIY frame, GIF,
effect, clock) -- never redraw-gated. eco_brightness is live and is the
ordinary brightness scale (not a separate or reduced one); eco OFF restores
the host's pinned brightness; eco is a one-shot dim, not a clamp (a host
brightness write during an active eco window wins outright); the eco
configuration is autonomous device state that survives a BLE disconnect with
no host attached; eco does NOT alter the clock's rendered colour. A
follow-up open question surfaced by this same run: whether eco affects the
clock's colour-CYCLING behavior over a longer window than these probes held
(the colour phases here only ran ~25s each) is not fully excluded -- see the
new follow-up below. Full account in capabilities.py's
common.set_brightness and eco.set_mode entries.

**P17b's CLOCK-STYLE SECTION IS VOID AS A BLOCK (2026-07-28).** Its phases
9-12 reported that style selection "appeared inert" and that STYLE_COLOR
paints the background with black digit cutouts, and its lux figures for
those phases were read as corroborating the second claim. P19 G3/G3b
overturned both: all eight styles render as distinct faces, and the colour
argument colours the DIGITS on every style. P17b separated those phases with
scoreboard labels, which are themselves native-mode commands -- and a label
on the panel produces exactly the near-full-panel lux reading that was taken
as evidence of a filled background. The lux corroborated the label, not the
style. Void the reading, the background claim, and those phases' lux figures
together; the brightness/eco results above are unaffected (different
phases, no style argument in play). See P19 below and
capabilities.py's clock.style_select.

**New follow-ups queued from this session:**
- **Clock-colour cycling window.** P17b's colour phases (9-12) held each
  state ~25s and found no colour change from eco; that rules out an
  immediate eco-colour interaction but not a slower one. A longer-hold
  variant (multi-minute per phase) would close the gap. Overlaps the passive
  magenta watch in P19.
- ~~Clock-style sweep, all eight values.~~ **DONE — see P19's closed G3.**

## P18 — Add recovery and lifecycle actions to the HCI capture  ⬜ OPEN

Still open after P1: that session captured commands, not lifecycle. A second
capture should record reconnect after intentional app disconnect, Bluetooth
toggle/resume, explicit DIY enter → frame → exit, a **repeated identical GIF
upload** (P1 contained no true duplicate, so our dedup findings are still
unconfirmed against the app), and any alarm/schedule disable action the app
offers.

Cost: negligible on a second capture run. Broadens the evidence from
command-byte discovery into initialization, persistence, transfer, and recovery.

## P19 — Second-pass follow-ups  ✅ CLOSED 2026-07-28 (G1-G5, G7; deferred tail below)

Re-cut 2026-07-27 after the post-audit pass on the display-durability effect,
then worked through with the operator at the panel on the night of
2026-07-27/28, and **consolidated and partly retracted on 2026-07-28**. Closed
items are recorded here as closed rather than deleted, so nobody re-queues them.
Each item is self-contained; batch into any session's tail the way P7 bundled
its odds and ends.

**RETRACTION, read this before anything else in P19.** The model this section
was cut against — "the first-connection shadow", display state set on a client
session's FIRST BLE connection being non-durable and the effect being scoped
per-client-session — is **WRONG and is withdrawn.** It was an over-elaboration
of a device property this lab had already recorded on 2026-07-12 and
2026-07-17: the panel commits its current display mode to flash **lazily**, and
a clean BLE disconnect reverts it to the last persisted mode. The
session-scoped framing came from uncontrolled elapsed time between commands,
which nothing held constant until G5. The corrected model — two independent
sufficient conditions, DWELL and a PRIOR RECONNECT — and the full evidence
table live in capabilities.py's display.persistence_matrix. **Lesson, recorded
deliberately:** before naming a new phenomenon, check the `glanceos-hardware-facts`
record and the 07-12/07-17 hardware entries. A "new" durability effect on this
panel is far more likely to be an old one seen from a new angle.

**THE SETTLED MODEL, as of the late-2026-07-28 pass.** Read this before any of
the item-by-item notes below, because several of them were written against
earlier drafts of it.

*Three distinct device states*, previously conflated and the largest single
source of confusion in the series:

| state | survives BLE reconnect? | survives power cycle? |
|---|---|---|
| GIF storage slot | yes | **yes** — seed-215 still recognised (status 3) afterwards |
| Active display mode | reasserts on reconnect | no — cleared |
| Flash / boot display state | **not** what a reconnect restores | **yes** — the panel boots to it |

All three disagreed at the same moment: after a power cycle the panel booted
straight to **orange** with no noise flash, while the GIF slot still held
seed-215 and a BLE reconnect minutes earlier had reverted to **noise**. This
also reconciles "fullscreen colour flash-persisted 3 days" (2026-07-17) with
"colour dies on reconnects" (2026-07-28) — boot state versus the active mode
reasserting. They were never in conflict.

*Two independent sufficient conditions.* A display write survives a
disconnect/reconnect if **either** holds:

- **(A) Dwell, in a session with no prior reconnect.** Threshold bracketed at
  **100 s < t ≤ 180 s** by the `own-delayed` ladder: 8, 30, 60, 75, 90 and
  100 s all DIED; 180 s SURVIVED. Confirms the 2026-07-12 "under ~3 min"
  record, which was right all along.
- **(B) A prior disconnect/reconnect earlier in the same session.** Durable
  almost immediately — **10 s is enough** (G7). Previously shown only for GIFs
  (`--preamble ble gif`, twice), now shown for fullscreen colour too.

*The protocol rule*, learned the hard way twice (see G7 and the retractions
under G5): to ask "did this write survive?", the **PERSISTED** state must
differ from what is being written — not merely the *active* one — and
establishing that costs a full commit period of its own, so **a valid isolated
trial is ~6 minutes, not 2**. Making a decoy *visible* is not the same as
making it *committed*.

**Answered / cancelled — do not re-run:**

- **`--preamble power gif`.** RUN, and it DIED: a `turn_off`/`turn_on` over the
  SAME BLE connection does not protect subsequently-written content, so the
  cheap power-blink mitigation is off the table. Only a genuine
  disconnect/reconnect does (condition B), or dwell (condition A). Full
  account, with the evidence table, in capabilities.py's
  display.persistence_matrix.
- **The P7 phase-9 fullscreen-colour retest.** CANCELLED. `--no-reset color`
  ran phase 9's scenario from the other direction and died, and the matrix
  colour row — armed with a prior reconnect behind it — held, so phase 9 is a
  short-dwell loss and colour volatility is dead as a hypothesis. Re-running it
  would only re-answer an answered discriminator. See capabilities.py's
  color.show.
- **G1 — brightness's class.** RUN 2026-07-28, `probe_p11_persistence.py
  --no-reset brightness`, twice. **BRIGHTNESS IS CONFIG-CLASS.** The white
  field armed with it died at the BLE reconnect (display-class, expected); the
  DIMMING SURVIVED, and survived the software power cycle after it as well, and
  separately survived a PHYSICAL mains power cut. That second cell is a VALID
  measurement, not a void one: the void-second-column rule applies only to
  state interruption 1 had already killed, and brightness was still in force.
  Brightness is flash-backed; pinning it once at startup is safe. See
  capabilities.py's common.set_brightness.
- **G1b — is the effect per-client-session? RETRACTED.** This was recorded as
  "**TWO instances: YES, strictly per-client-session**", on the strength of
  foreign sessions failing to kill content they had not written. **That claim
  is withdrawn.** Those runs all had minutes of elapsed time behind them, so
  they satisfied condition (A) — dwell — and prove nothing about session
  identity. G5's `own-delayed` ladder then showed the *same* session failing
  to kill its own **180-second-old** content, holding session identity constant
  and varying only the delay. Session identity is not the variable. Consequence
  for integrators: multiple clients CAN share this panel, but the reason is
  dwell, not ownership. See display.persistence_matrix. *Note:* the retraction
  originally rested on a 90 s run that is itself now withdrawn as
  flash-confounded; the 180 s ladder point carries it instead, so the
  conclusion stands on re-anchored evidence.
- **G2 — shadow-recover: pointer or payload?** RUN 2026-07-28,
  `probe_p11_persistence.py shadow-recover` (the mode name is a legacy label
  from the retracted model, kept because it is the CLI handle). **POINTER, NOT
  PAYLOAD.** Operator saw HOP -> CLOCK -> HOP -> HOP: the short-dwell GIF died
  at the reconnect, `gif.activate_stored()` with the same bytes and NO
  re-upload brought it back and it actually rendered, and a control reconnect
  proved the restore durable. Nothing is destroyed -- only the current-mode
  pointer is committed lazily. SDK recovery rule: **RE-ACTIVATE, DO NOT
  RE-TRANSFER**, with the caveat that it only applies to content that HAS a
  re-activate path (a parked DIY still has none). See gif.upload_file.
- **G3 — sweep all eight clock styles.** RUN 2026-07-28,
  `probe_p19_g3_clock_styles.py sweep`, unlabelled, colour white. **All eight
  rendered as DISTINCT faces** ("all the faces from the app"), all eight
  acked. `clock.style_select` moves UNKNOWN -> VERIFIED on all 8 values, and
  the candidate-KNOWN_BROKEN framing is deleted, not softened. P17b's
  contrary reading was label-contaminated (see the P17 correction above).
- **G3b — where does the colour argument land?** RUN 2026-07-28,
  `probe_p19_g3_clock_styles.py sweep-red`, identical to `sweep` but for the
  colour. **ALL RED DIGITS, no background fill anywhere, including
  STYLE_COLOR.** The colour argument colours the DIGITS on every style; the
  vendor app agrees (one colour setting, digits, no background option). The
  "STYLE_COLOR paints the background" claim is deleted. Reinstating a
  background-fill claim for any style requires a RED-equivalent reproduction
  -- white is useless for this question.
- **G3c — styles 6 and 7 ANIMATE.** Observed during the red sweep:
  STYLE_OUTLINES (6) and STYLE_RGB_CORNERS (7) blink / have a heartbeat, and
  their colours read slightly off from the app's. First record of any clock
  style animating; the colour mismatch is noted and not chased. The magenta
  hypothesis that the `RGB_*` styles free-run through hues was **FALSIFIED**
  (style 0 rendered plain red digits), so magenta stays open -- see the
  passive watch, still queued below.
- **G4 — does an armed schedule theme silence set_time's acks?** RUN
  2026-07-28, `probe_p19_g4_settime_acks.py full`. **The theme is not the
  variable: `set_time` is UNCONDITIONALLY ack-silent.** Zero acks on all seven
  jumps -- three armed, three with both slots disarmed and the master switch
  off, plus a pre-arm jump -- at a 2.5 s settle with the ack list never read
  early. P5's two-ack reading is SUPERSEDED (probable ack-attribution
  artifact). Not a hang hazard, but every call was paying the transport's
  2.0 s ack timeout, so `client.set_time` is now fire-and-forget
  (`verify=False`). See capabilities.py's common.set_time and
  common.ack_timing.
- **G5 — what is the kill event?** RUN 2026-07-28,
  `probe_p19_g5_kill_event.py`, both sequences, then `own-delayed` again as a
  dwell ladder. **This is the probe that falsified the session-bound model**,
  and the one that forced the whole P19 retraction above. `reconnect` (a
  foreign process reconnecting on content it did not write, minutes old)
  SURVIVED, which the session-bound reading had predicted -- but the ladder
  showed the SAME session unable to kill its own 180-second-old content, which
  it had not. Session identity held constant, dwell the only variable:
  **elapsed time is the variable, not ownership.** That plus the
  `--preamble ble` result gives the two-condition model.
  **THE DWELL LADDER, one trial per invocation** (a second trial in the same
  process would be rescued by the first process's own reconnect, i.e. by
  condition (B)): **8, 30, 60, 75, 90, 100 s all DIED; 180 s SURVIVED**, so
  **100 s < t ≤ 180 s**. Not narrowed further, deliberately — see the open
  questions.
  **TWO RUNS RETRACTED, do not count them as evidence in either direction:**
  `own-delayed 140` and the `own-delayed 60` rerun both wrote ORANGE while
  orange was already the flash state, so reversion and survival were the same
  picture. The 60 s rerun was the worse of the two — it activated a noise GIF
  as a decoy, but the decoy had only ~10 s, nowhere near a commit, so flash
  still held orange underneath (which is also how G7's `activate_stored`
  finding surfaced). **The earlier "90 s survived" reading is withdrawn for
  the same reason** and is the one that first sent the model astray; the
  ladder's 90 s point, run under a valid discriminator, DIED.
- **G7 — a properly isolated dwell trial.** RUN 2026-07-28,
  `probe_p19_g7_isolated_dwell.py trial` (dwell 10 s). Written specifically to
  satisfy the protocol rule above: persist a noise decoy for 200 s, reconnect
  and VERIFY it, then write GREEN, hold 10 s, reconnect. Operator:
  `noise -> reconnect -> ORANGE -> green -> reconnect -> GREEN -> clock`. Two
  findings:
  1. **`gif.activate_stored()` does NOT commit the GIF it activates.** Watch #1
     showed ORANGE, not noise: the decoy had been the *active* display for a
     full 200 s — longer than the 180 s that committed orange in the ladder —
     and flash still held orange from that earlier trial. Activating switches
     playback without arming whatever the commit path is. Observed once;
     mechanism OPEN, recorded rather than explained. See gif.upload_file.
  2. **Condition (B) confirmed for fullscreen colour.** Watch #2 showed GREEN:
     a 10-second-old write SURVIVED, where the same 10 s in a first-connection
     session sits well inside the ladder's six consecutive deaths. The only
     thing this session had that those lacked is the step-2 reconnect.
  **The run is NOT void despite (1)** — and this is the part worth keeping.
  Green differs from BOTH candidate revert targets: a lost write would have
  shown orange (flash) or noise (active), and neither appeared, so watch #2
  reads cleanly whichever would have won. The discriminator survived its own
  premise failing.

**LESSON, now a probe house rule (from G3/G3b):** an on-panel label is itself
a mode-changing command. Scoreboard and text labels are a legitimate way to
disambiguate phases, but they are UNSAFE in any probe whose subject is native
mode state -- here they manufactured a false KNOWN_BROKEN candidate that
survived in the capability table for a day, and then a lux reading appeared to
corroborate it because both instruments shared the same confound. Prefer
console-timestamped unlabelled sweeps whenever the measurement lives in the
same mode the label would occupy. This raises the value of the label-free
chronograph rerun in the deferred tail: P7's own caveat is now MORE likely,
not less.

**OPEN QUESTIONS, as of the 2026-07-28 consolidation:**

1. ~~**Bisect the dwell threshold.**~~ **ANSWERED, and closed on purpose.** The
   ladder brackets it at **100 s < t ≤ 180 s** (G5 above). **Narrowing it
   further is NOT worth more panel time**: a valid isolated trial now costs
   ~6 minutes each, and the guidance — allow ~3 minutes, or reconnect once
   first — does not change anywhere inside that band. The drill
   `D:\glanceos\glanceosd\drills\measure_persistence_dwell.py` stays unrun.
2. **Why does a prior reconnect rescue a 10-second-old write?** Reproduced for
   GIFs twice and now for fullscreen colour (G7); dwell cannot explain it (same
   ~10 s, opposite outcome against six ladder deaths), and on the 07-28 GIF run
   the animation **continued from where it was** rather than restarting, so the
   device did not re-initialise playback across the disconnect at all.
   Mechanism unknown. This is the load-bearing evidence for GlanceOS's
   double-tap connect, so it matters. An HCI capture comparing connection 1
   with connection 2 is the definitive tool (see the deferred tail below).
3. **Why does `gif.activate_stored()` not commit the GIF it activates?**
   Observed once (G7): 200 s as the active display, flash unchanged. Whatever
   arms the commit path is not armed by activation. Cheap to re-observe as a
   rider on any future GIF probe; not worth a dedicated session of its own.
4. **Does the dwell differ by content type?** GIF (a stored payload),
   fullscreen colour (~3 bytes), and DIY frames (never persisted at all, per
   07-17) plausibly commit on different schedules. The ladder measured
   fullscreen colour only.
5. **The magenta digits** remain unexplained. Passive watch: leave a static
   clock face up and glance at it occasionally through a session, sending no
   commands once the face is up. Tests whether the face cycles colour on its
   own over time -- the last standing candidate, now that eco, clock style
   selection, the default colour argument, low-brightness channel dropout, AND
   RGB-style hue cycling (G3c's falsified prediction) are all excluded
   (capabilities.py's eco.lowlight_no_colour_shift and clock.style_select).
6. **P11's DIY row across a software power cycle** is still a void cell (see
   the deferred tail).
7. **The `set` / `check` / `restore` handoff path is dwell-confounded** for
   display-class rows. `set` runs in its own process and rejects `--preamble`,
   so any display content it establishes is subject to conditions (A)/(B)
   before the operator even gets up from the desk. Only config-class rows
   (brightness, eco) are safe on that path as it stands. Worse than first
   recorded, now that the protocol rule is understood: a valid display-class
   trial on that path needs the *persisted* state to differ from what is
   written, which the handoff workflow has no way to establish.

**Deferred tail (unchanged, no probe written):**

- **P11's physical power-cycle column.** Pulling mains power at the wall has
  not been run for any of this matrix's rows -- P6's Q4 physical power-cycle
  covered Timer alarms only. Use the `set` / power-cycle / `check` / `restore`
  operator workflow `probe_p11_persistence.py` already documents. ~15 min,
  operator must be present.
- **The DIY row re-test for the void cell.** Re-run the DIY row alone with its
  state re-established BETWEEN interruption 1 and interruption 2, so the
  software-power-cycle cell measures something. While there, confirm no other
  row's chained cell is compromised the same way (desk review: was any other
  row's BLE-reconnect reading ambiguous?).
- **An interruption-order knob for P11**, so a row can be power-cycled before
  it is BLE-interrupted rather than always after. That is the general fix for
  the void-cell class of flaw, of which the DIY cell and the short-dwell runs
  that died at interruption 1 are both instances.
- **An HCI capture of connection 1 versus connection 2.** The prior-reconnect
  rescue (condition B) is unexplained and nothing in our stack distinguishes
  the two connections (verified against `client.py`/`transport/ble.py`). A
  capture is the only remaining way to see whether the DEVICE distinguishes
  them. No longer optional -- it is the definitive tool for open question 2.
- **Label-free rerun of the countdown/chronograph branch.** P7's
  countdown-pause / chronograph-start sequence did NOT reproduce the
  2026-07-20 "paused countdown hijacks chronograph" report, but the probe's
  own author predicted in advance that the scoreboard phase labels narrating
  each step are themselves native-mode commands that could clear the shared
  timer state before the interaction under test ever ran. Rerun with zero
  scoreboard/display calls between the countdown pause and the chronograph
  commands before recording the independence claim as settled either way. Same
  label hazard G3 is designed around. ~5 min.
- **Effect-feeding.** P12 sequence 3 found the running rainbow effect visibly
  DRAGGED a naive injected frame into its own falling animation rather than
  overwriting it -- the effect operates on the LIVE framebuffer. Speculative
  and UNPROBED: write a frame, start an effect, and see whether the effect
  animates the caller's own pixels rather than its built-in palette. Not a
  capability until tested. ~10 min.

**Password probes remain LAST-OF-ALL** and are not part of any queue above:
`set_password` / `verify_password` carry a lockout risk with no known factory
reset.




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
