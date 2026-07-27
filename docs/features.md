# Feature Guide

One section per `IDotMatrixClient` namespace. Every method example below
assumes an open connection:

```python
async with IDotMatrixClient.connect_to(device, ScreenSize.SIZE_32x32) as client:
    ...  # the snippets below go here
```

Status tags (✅ verified / ⚠ source-derived / ❓ unknown / ✖ known-broken) are
quoted from `pyidotmatrix/capabilities.py` — the evidence-backed source of
truth, never upgraded or invented here. Full evidence strings and how to
extend a status: [Hardware Compatibility](hardware-compatibility.md).

Only one native mode (clock, text, effect, or the DIY framebuffer) is active
on the panel at a time — calling into a different namespace switches the
panel's active mode. See
[Protocol Notes § Persistence](protocol-notes.md#persistence-and-durability)
for what survives that switch and what doesn't.

> ⚠ **Write content, then don't disconnect immediately.** Whatever the panel
> is *showing* commits to flash lazily; a clean disconnect a few seconds after
> a write reverts the panel to its previously persisted mode, silently, with
> a successful ack. Details and the two ways to avoid it:
> [Protocol Notes § Display-class state](protocol-notes.md#display-class-state--lazily-persisted-and-losable).

## `display` — raw framebuffer

The pixel surface: full frames and partial pixel updates. `client.display`
is a `BleDisplay`; the same interface (`DisplayBackend`) is satisfied by
`SimulatorDisplay` for hardware-free development.

**Status:** ✅ `show_frame`, ✅ `set_pixels` (both hardware-verified). See
[Streaming & performance](protocol-notes.md#streaming--performance) before
building anything that pushes frames continuously — the device caps DIY
frame rendering at ~1.75 fps regardless of send rate; sustained animation
belongs to the pixel-delta path, not full frames.

```python
await client.display.show_frame(rgb_bytes)                  # exact width*height*3 RGB bytes
await client.display.set_pixels((255, 0, 0), [(0, 0), (1, 1)])   # partial update, unacked by default

# convenience: adapt an arbitrary image/path to the screen and show it as a frame
await client.show_image("photo.png")
```

`display.set_pixels` batches automatically at the device's 255-pixel/command
cap — pass as many coordinates as you like.

## `clock` — native clock face

**Status:** ✅ verified, including **all eight styles**. Ticks on the device's
own RTC through disconnects; **not** flash-persisted (a power-cycle or long
enough disconnect loses it — see
[Protocol Notes § Persistence](protocol-notes.md#persistence-and-durability)).

```python
from pyidotmatrix.protocol import clock

await client.clock.show(
    style=clock.STYLE_RGB_SWIPE_OUTLINE,   # 8 styles, 0..7
    show_date=True,
    hour24=True,
    color=(255, 255, 255),
)
```

All eight styles (`0` RGB swipe outline, `1` Christmas tree, `2` checkers,
`3` colour, `4` hourglass, `5` alarm clock, `6` outlines, `7` RGB corners)
render as visually distinct faces — the same set the vendor app offers.
Styles **6 and 7 animate** (blinking pixels / a heartbeat); the other six are
static.

**`color` sets the colour of the DIGITS, on every style.** There is no
background-fill behaviour on any style, including `STYLE_COLOR` — the vendor
app likewise exposes exactly one colour setting and no background option.

Set the device's RTC first (`client.common.set_time`) if you care about it
showing the right time.

## `text` — device-rendered scrolling text

**Status:** ✅ verified (full arc documented in
`pyidotmatrix/protocol/text.py` and `capabilities.py`). The client
automatically selects the per-panel-size wire format — on 32×32 this matters:
the generic/legacy builder used on other sizes renders **truncated** here.

```python
from pyidotmatrix.protocol import text

await client.text.show(
    "HELLO",
    font_path="/path/to/font.ttf",   # caller-supplied TTF; required
    font_size=16,
    text_mode=text.MODE_MARQUEE,     # 9 modes: replace, marquee, reversed marquee,
                                      # vertical rising/lowering, blinking, fading,
                                      # tetris, filling
    speed=95,                         # packet speed byte; 100 measured smoothest on 32x32
    color_mode=text.COLOR_WHITE,      # 6 modes: white, RGB, and 4 rainbow variants
    color=(255, 255, 255),
    bg_color=None,
)
```

Text is rasterized host-side into fixed 16×32 1-bit cells (no anti-aliasing,
no kerning) and animated/colorized device-side. `common.set_speed` has **no**
effect on a running text animation — the packet's own `speed` byte is what
governs marquee smoothness.

No font ships with this package: `font_path` is a caller-supplied TTF/OTF, and
without one you're at the mercy of whatever Pillow resolves on the host —
pass an explicit path for reproducible output. The rasterization step itself
is CI-verified byte-stable across platforms given the same font (unlike the
`gif` feature's re-encoding, whose Pillow GIF encoder is not).

## `gif` — GIF upload + native playback

**Status:** ✅ verified. Chunked upload, native on-device playback and
looping.

```python
from pyidotmatrix.imaging import ResizeMode

await client.gif.upload_file(
    "nyan.gif",
    resize_mode=ResizeMode.FIT,   # FIT / FILL / STRETCH
    do_palettize=True,
    background_color=(0, 0, 0),
    duration_per_frame_ms=None,   # None keeps the source GIF's own timing
)

# already-adapted GIF bytes (skip SDK-side re-processing):
await client.gif.upload_bytes(gif_bytes)
```

**If a GIF disappears after a reconnect, re-activate it — don't re-upload
it.** Only the panel's current-mode pointer is lost; the uploaded payload
survives on the device and is recognized by its CRC:

```python
restored = await client.gif.activate_stored(gif_bytes)   # True: no transfer needed
```

You pass the same bytes so the device can match their CRC; it recognizes the
payload it already holds and re-renders it without a re-transfer.

See [Protocol Notes § Recovery](protocol-notes.md#recovery-re-activate-dont-re-transfer).

SDK-side caps: 64 frames, 2 s total duration (evenly sampled if the source is
longer), re-encoded with `optimize=True` — the device requires an optimized
GIF encoding. Frame resizing uses NEAREST unconditionally, so photographic
GIFs come out blocky; this is a known future improvement, not a bug (see
ROADMAP §6).

## `chronograph` — stopwatch

**Status:** ✅ verified. Counts up on the panel once started; runs
autonomously on the device.

```python
await client.chronograph.reset()
await client.chronograph.start()
await client.chronograph.pause()
await client.chronograph.resume()
```

Caveat: starting after a pause **restarts from zero** rather than resuming —
hardware-observed, not an SDK bug. Chronograph and countdown share
device-side timer state; a paused countdown can be affected by chronograph
commands.

## `countdown` — timer

**Status:** ✅ verified. Runs autonomously on the device and auto-returns to
the clock at zero.

```python
await client.countdown.start(minutes=25, seconds=0)   # a Pomodoro
await client.countdown.pause()
await client.countdown.restart()
await client.countdown.stop()
```

## `scoreboard` — two-digit score display

**Status:** ✅ verified. Each side is 0–999.

```python
await client.scoreboard.show(count1=12, count2=34)
```

## `eco` — scheduled dimming

**Status:** ✅ verified. A daily window during which the panel dims to a
lower brightness.

```python
await client.eco.set_mode(
    enabled=True,
    start_hour=22, start_minute=0,
    end_hour=6, end_minute=0,
    eco_brightness=10,
)
```

## `color` — fullscreen color

**Status:** ✅ verified. Fills the panel with one solid color. Once persisted
it **flash-persists** across a power-cycle (observed surviving multiple days)
— different from every other mode kind except effects. Like every display-class
mode, it is losable if you disconnect within seconds of writing it; see
[Protocol Notes § Persistence](protocol-notes.md#persistence-and-durability).

```python
await client.color.show((255, 0, 128))
```

## `graffiti` — mirrored/transformed pixel draws

**Status:** ✅ verified (including the header's `move_type` byte, mapped
2026-07-21). This is a variant of the same delta path as `display.set_pixels`
that adds optional mirroring.

```python
from pyidotmatrix.protocol import graffiti

await client.graffiti.set_pixels(
    (0, 255, 0),
    [(1, 1), (2, 2)],
    move_type=graffiti.MOVE_HORIZONTAL_MIRROR,   # MOVE_NONE / MOVE_HORIZONTAL_MIRROR / MOVE_VERTICAL_MIRROR
)
```

`MOVE_HORIZONTAL_MIRROR`/`MOVE_VERTICAL_MIRROR` draw the given pixels **plus**
a mirrored copy across the panel's center axis — hardware-confirmed with a
single-pixel discriminator. This call is genuinely ack-silent on the wire;
the client never opens an ack wait for it regardless of
`verify_commands`.

## `effect` — built-in lighting effects

**Status:** ✅ verified for activation (`show`) **and for `speed`**; ✖
known-broken for the vendor app's chunked framing (`show_chunked`).

```python
from pyidotmatrix.protocol import effect

await client.effect.show(
    style=2,                       # 7 styles, 0..6
    colors=[(255, 0, 0), (0, 255, 0)],   # 2..7 colors
    speed=effect.SPEED_DEFAULT,    # 90 — the app's own default
)
```

`speed` is byte 5 of the effect command and it genuinely works: a five-point
sweep produced a monotonic animation-rate curve, matching the vendor app,
whose speed dial re-sends the whole effect command with a new byte 5. This
capability spent a while marked broken because an early probe sent a
malformed length byte; the byte was always fine, the builder wasn't. Note
there is no standalone "set speed" command — `common.set_speed` is dead code
that the vendor app never sends; change speed by re-issuing `show()`.

`show_chunked` — the app's bespoke chunked effect framing — is acked but
produced no visible effect; `show()` is the hardware-proven path.

## `music_sync` — onboard-mic reactive lighting

**Status:** ✅ `send_rhythm_levels` and `set_mic_type` verified; ⚠
`stop_rhythm` source-derived; ✖ `send_image_rhythm` known-broken (acked, no
figure appeared, stuttered the clock face).

The music screen works phone-side, not device-side: **your program** does the
FFT and streams 16 level bytes to the panel at ~10 Hz. That renders cold from
the clock with no mode entry at all. `set_mic_type` selects a different
visualization for the same stream — only value `1` has been exercised, so what
the other values pick is unknown. The stream is unacked; pace it yourself
(~10 frames/second is what the app does). The per-band → pixel mapping (how
many columns, which geometry) is still unmapped.

```python
await client.music_sync.set_mic_type(1)        # 6-byte frame, value defaults to 100
await client.music_sync.send_rhythm_levels([0, 3, 7, 13, 10, 5, 2, 1,
                                            1, 2, 5, 10, 13, 7, 3, 0])
await client.music_sync.send_image_rhythm(5)   # known not to work — see above
await client.music_sync.stop_rhythm()
```

## `common` — device settings

**Status:** mixed — see the per-method table below. This is the "junk
drawer" namespace: brightness, power, RTC, flip, reset, plus several
commands proven inert on the reference panel.

```python
await client.common.set_brightness(60)          # ✅ 5-100%, out-of-range nacked
await client.common.turn_on()                    # ✅
await client.common.turn_off()                    # ✅
await client.common.set_screen_flipped(True)      # ✅ verified upside-down/righted
await client.common.set_time(datetime.now())      # ✅ RTC sync; never acks (see below)
await client.common.reset()                        # ✅ used live to clear a stuck state

await client.common.freeze_screen()               # ✖ acked, no observable effect
await client.common.set_speed(50)                  # ✖ acked, no effect on text or effects
await client.common.set_screen_timeout(30)          # ✖ no ack, no effect on this panel
await client.common.read_screen_timeout()            # ✖ same — family unsupported here

await client.common.set_joint(0)                    # ❓ purpose unknown even upstream

await client.common.set_password(123456)             # ⚠ NEVER exercised on hardware —
await client.common.verify_password(123456)           #    see the warning below
```

**Brightness accepts 5–100 and nacks anything outside that**, but the *usable*
dynamic range is roughly **5 to ~42**: above about 42 the output is
effectively flat, and 50 through 100 are visually indistinguishable. If you
want a night mode, aim at 5–15; if you want "bright", 42 already gets you
there. The setting is flash-backed — it survives disconnects and even a
physical power cut, so pin it once and leave it.

**`set_time` never acks.** Zero acks across seven RTC jumps, armed and
unarmed schedule state alike, so the client sends it fire-and-forget rather
than burning a 2 s ack timeout on every call. Don't await one, and don't read
the silence as failure — the RTC does get set.

**Set `client.common.set_time` before relying on any alarm or schedule
firing at the intended wall-clock time** — Timer/Schedule evaluate against
the device's own RTC, including its weekday.

> ⚠ **Do not experiment with `set_password`/`verify_password` on hardware.**
> The wire bytes are source-confirmed but this pair has never been sent to a
> real device — the maintainer sequenced it deliberately last across the
> entire project roadmap because a wrong guess about the password protocol's
> semantics could lock a panel out of its own driver, with no known
> factory-reset path. If you choose to probe this yourself, you accept that
> risk. `verify_password` is also always fire-and-forget in this client
> (`verify=False` internally) because its ack key collides with graffiti's
> nack — see the method's docstring in `pyidotmatrix/client.py`.

## `experimental` — unverified and/or destructive

Everything here is bytes confirmed from the decompiled vendor app but not
(or only partially) exercised against real reference hardware, or explicitly
destructive. Exempt from SemVer guarantees — anything here can change or
disappear without a major-version bump (see `docs/ROADMAP.md` §15).

**Alarms (Timer slots)** — ✅ verified, arguably the most mature thing in
this namespace despite the label:

```python
from pyidotmatrix.protocol import timer

alarm = timer.Timer(
    num=0, week=timer.build_timer_week([0, 1, 2, 3, 4]),  # Mon-Fri, enabled
    hour=7, minute=30,
    duration_bucket=timer.DURATION_30S,
    content_type=timer.CONTENT_GIF,
    buzzer_enable=True,
)
await client.experimental.timer_set(alarm, gif_bytes)   # gif_bytes: an encoded GIF bytestream
await client.experimental.timer_close(alarm)             # PARTIAL disarm — see below
```

Three things to know before you build on alarms:

- **They are config-class: flash-persistent.** An armed slot survives a
  physical power cut with its content intact and fires after the panel boots
  back up. You do not need a host attached for an alarm to go off.
- **`timer_close` is a partial disarm.** It clears the slot's *content* but
  leaves its schedule and buzzer armed — a closed slot still buzzes at its
  appointed minute. If you need silence, don't rely on `timer_close` alone.
- **Same-minute collisions: the higher slot index wins the display, and both
  buzzers fire.** The loser's content never reaches the panel at all. Put the
  alarm you actually want *seen* in the higher slot index.

`CONTENT_GIF` payloads must be an encoded GIF bytestream (confirmed:
animates + buzzer at fire time). `CONTENT_IMAGE` payloads must be an encoded
**PNG** bytestream, not raw RGB (confirmed: raw RGB saves but never renders).
`CONTENT_TEXT` is unmapped — the decompile's offsets aren't trustworthy.

**Weekly schedule** — ✅ verified for GIF theme upload/fire, ⚠ for the master
switch and PNG image content:

```python
from pyidotmatrix.protocol import schedule

theme = schedule.ScheduleTheme(...)   # see protocol/schedule.py for full fields
await client.experimental.schedule_set_theme(theme, gif_bytes, schedule.CONTENT_GIF)
await client.experimental.schedule_master_switch(enable=True, buzzer=True)
```

**Everything else here** — ✖/⚠, use with the status tag in mind:

```python
await client.experimental.set_time_indicator(True)   # ✖ acked, nothing visible

# ⚠ DESTRUCTIVE and never hardware-verified. Requires confirm=True.
await client.experimental.delete_device_data(confirm=True)
```

## See also

- [Hardware Compatibility](hardware-compatibility.md) — the full table this
  page's status tags are drawn from, with dated evidence per row.
- [API Reference](api-reference.md) — exact method signatures.
- [Protocol Notes](protocol-notes.md) — why acks aren't proof of effect, and
  what persists across a disconnect (and what silently doesn't).
