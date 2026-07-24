"""Per-feature capability and hardware-verification table (ROADMAP.md section 8).

Static, versioned data: each entry records how far a command's behavior has
actually been established -- decompiled-source evidence, live-probe evidence,
or a documented failure -- and on which panel size. The table is maintained
from evidence only (probe scripts in probes/, the RE docs in
docs/reverse-engineering/, and ROADMAP.md section 3's dated inventory); it is
never populated by runtime feature-probing, because the device acks commands
it does not act on (hardware doctrine, ROADMAP.md section 4).

This module is read-only reference data. It does not gate any client call --
consulting it to raise UnsupportedFeatureError early is a later milestone
(ROADMAP.md section 8's strategy recommendation).

    >>> from pyidotmatrix import capability
    >>> capability("text.show").status
    <CapabilityStatus.VERIFIED: 'verified'>

Statuses:
    VERIFIED        observed doing the right thing on real hardware (entry
                    says which screen size; other sizes are still unknown).
    SOURCE_DERIVED  byte layout confirmed from the decompiled vendor app but
                    never (or not conclusively) exercised on hardware.
    UNKNOWN         wire bytes exist but their meaning or effect is
                    unestablished even in the app source.
    KNOWN_BROKEN    sent to real hardware and observed NOT working there.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from pyidotmatrix.screen import ScreenSize

__all__ = ["Capability", "CapabilityStatus", "CAPABILITIES", "capability"]


class CapabilityStatus(Enum):
    """How a command's behavior has been established. See module docstring."""

    VERIFIED = "verified"
    SOURCE_DERIVED = "source_derived"
    UNKNOWN = "unknown"
    KNOWN_BROKEN = "known_broken"


@dataclass(frozen=True)
class Capability:
    """One row of the capability table.

    feature      client namespace the command lives on (e.g. "text", "common").
    command      method or sub-behavior name within that namespace.
    status       see CapabilityStatus.
    screen_size  the panel size the status statement applies to; None means the
                 statement is size-independent (typically because the only
                 evidence is decompiled source, which is size-agnostic).
    evidence     where the status comes from: probe script, RE doc section,
                 or a dated hardware session -- never a guess.
    """

    feature: str
    command: str
    status: CapabilityStatus
    screen_size: ScreenSize | None
    evidence: str

    @property
    def name(self) -> str:
        return f"{self.feature}.{self.command}"


_S32 = ScreenSize.SIZE_32x32

_ENTRIES: tuple[Capability, ...] = (
    # --- display (framebuffer pipeline) ---
    Capability(
        "display", "show_frame", CapabilityStatus.VERIFIED, _S32,
        "DIY full-frame upload is GlanceOS's main render path; ~1.5 s device processing with "
        "ack-as-flow-control (ROADMAP.md section 3 Display; FEATURE_MATRIX.md Display/rendering). "
        "Streaming benchmark 2026-07-20 (probes/probe_streaming_benchmark.py): the device "
        "RENDERS full frames at a hard ~1.75 fps cap regardless of send rate or write mode; "
        "under an unacked flood it samples the latest frame, drops the rest, and its fa03 "
        "notifies track frames processed (~1.75/s), not frames received. Geometry contract "
        "verified 2026-07-24 (probes/probe_p8_geometry.py, two runs): the buffer is row-major "
        "from a top-left origin in RGB channel order, and graffiti pixel commands share this "
        "exact coordinate space (asymmetric corner + canary landmarks all landed as painted). "
        "PNG PAYLOADS ACCEPTED 2026-07-25 (vendor-app HCI capture, tools/parse_btsnoop.py): the "
        "app sent an 89-50-4e-47 RGBA 32x32 PNG under our exact 9-byte DIY header and the device "
        "acked it [05 00 00 00 01] -- so this path takes encoded PNG as well as the raw RGB "
        "buffer we send (same finding shape as timer CONTENT_IMAGE). Untested by us; our raw-RGB "
        "path is unaffected.",
    ),
    Capability(
        "display", "write_without_response", CapabilityStatus.VERIFIED, _S32,
        "fa02 advertises write-without-response and our panel honors it: unacked frames "
        "rendered on-screen during the 2026-07-20 streaming benchmark (operator-observed). "
        "Firmware-variant caveat: LumiSync's RE notes report no-response writes IGNORED on "
        "their unit, while idotmatrix-overclocked uses them successfully on a 64x64 -- treat "
        "as per-variant. Sustained flooding eventually dropped our BLE link twice; pace near "
        "the ~1.75 fps render cap.",
    ),
    Capability(
        "display", "set_pixels", CapabilityStatus.VERIFIED, _S32,
        "Graffiti delta path, ~20 ms unacked, <=255 px/command found by testing "
        "(ROADMAP.md section 3 Display; FEATURE_MATRIX.md Display/rendering).",
    ),
    Capability(
        "display", "diy_entry_no_clear", CapabilityStatus.KNOWN_BROKEN, _S32,
        "DIY entry mode 3 silently fails over effect/clock states while the device acks anyway "
        "(A/B 2026-07-17; 3-run clock probe 2026-07-19; probes/probe_diy_modes.py).",
    ),
    Capability(
        "display", "diy_quit_keep_frame", CapabilityStatus.VERIFIED, _S32,
        "DIY quit mode 2 parks a kept frame that survives clean disconnect but not power-cycle "
        "(2-run probe 2026-07-18; ROADMAP.md section 3 Display).",
    ),
    # --- native modes ---
    Capability(
        "chronograph", "set_mode", CapabilityStatus.VERIFIED, _S32,
        "Stopwatch counts up on panel; start-after-pause RESTARTS from zero rather than "
        "resuming (probes/probe_chronograph_clean.py, 2026-07-21). Caveat: with a paused "
        "countdown pending, chronograph commands acted on THAT state instead (sweep 2 "
        "2026-07-20) -- the native timer modes share device-side state.",
    ),
    Capability(
        "countdown", "set_mode", CapabilityStatus.VERIFIED, _S32,
        "30s countdown ran on panel, auto-returned to clock at zero; runs autonomously on "
        "device (probes/probe_capability_sweep1.py, 2026-07-20). MODE_DISABLE left resumable "
        "state rather than clearing (see chronograph caveat).",
    ),
    Capability(
        "clock", "show", CapabilityStatus.VERIFIED, _S32,
        "Clock ticks on RTC through disconnects; not flash-persisted (persistence probes "
        "2026-07-17; 3-run clock probe 2026-07-19; ROADMAP.md section 3 Native modes).",
    ),
    Capability(
        "scoreboard", "show", CapabilityStatus.VERIFIED, _S32,
        "12:34 rendered as two scores on panel (probes/probe_capability_sweep1.py, 2026-07-20).",
    ),
    Capability(
        "eco", "set_mode", CapabilityStatus.VERIFIED, _S32,
        "With the eco window covering now and eco_brightness=5, the panel visibly dimmed; "
        "disable restored brightness (probes/probe_capability_sweep3.py, 2026-07-21).",
    ),
    Capability(
        "color", "show", CapabilityStatus.VERIFIED, _S32,
        "Fullscreen color flash-persists across power-cycle -- survived 3 days, 2026-07 "
        "(persistence probes 2026-07-17; ROADMAP.md section 3 Display).",
    ),
    Capability(
        "graffiti", "set_pixels", CapabilityStatus.VERIFIED, _S32,
        "Hardware-verified delta-render path; genuinely ack-silent, so the transport never "
        "awaits an ack for it (ROADMAP.md section 3 Display; FEATURE_MATRIX.md). App usage "
        "2026-07-25 (vendor-app HCI capture, tools/parse_btsnoop.py): the paint screen's ERASER "
        "is not a protocol feature at all -- it is a normal draw of color #000000 with move=0, "
        "which matches the falsified byte-4 ERASE hypothesis (see graffiti.move_type). The app "
        "only ever emitted single-pixel 10-byte commands, never a multi-pixel batch.",
    ),
    Capability(
        "graffiti", "move_type", CapabilityStatus.VERIFIED, _S32,
        "Header byte 4 = the APK's DiyImageMoveType: 1 = HORIZONTAL_MIRROR, 2 = VERTICAL_MIRROR "
        "-- draws the pixels PLUS a mirrored copy across the panel's center axis (single-pixel "
        "discriminator, probes/probe_graffiti_transform{,2}.py, 2026-07-21). MAP COMPLETE "
        "2026-07-25 (probes/probe_graffiti_byte4_erase.py, dark-blue field): values 4-7 are all "
        "accepted silently and draw PLAIN -- no mirror, no motion, no erase, no nack. The ERASE "
        "hypothesis for 4 is FALSIFIED (white pixels re-sent with byte4=4 stayed white on a "
        "non-black field; same-color-resend caveat noted). Only 1/2 carry firmware semantics; "
        "0 and 3-7 draw plain, so the APK DiyImageMoveType names (OVERALL_MOVEMENT/ERASE) are "
        "app-side paint-tool labels, not firmware behavior. CORRECTION: the earlier 'recolors "
        "the command two back' theory (probe_graffiti_movetype*.py, 2026-07-20) was FALSE -- "
        "vertical mirroring onto symmetric probe layouts mimicked recoloring exactly; the "
        "single-pixel test killed it.",
    ),
    Capability(
        "graffiti", "byte3_required_one", CapabilityStatus.VERIFIED, _S32,
        "Header byte 3 is NOT a mirror field: only value 1 (the app's hardcoded constant) "
        "draws; 2 is nacked [5,0,5,2,0] (4/4 reproductions), 0/3/4 are acked and silently "
        "swallowed (probes/probe_graffiti_byte3_*.py, control case, 2026-07-21). CORRECTION of "
        "the 2026-07-12 sweep, whose re-sent same-coordinate pattern over a lit L made five "
        "no-ops look identical.",
    ),
    Capability(
        "effect", "show", CapabilityStatus.VERIFIED, _S32,
        "Effect mode activated live with the historical speed=90 during persistence probes "
        "2026-07-17 (ROADMAP.md section 3); header layout confirmed from "
        "MutilColorAgreement.java:42-72 (APK_SECOND_PASS.md Q5(a)).",
    ),
    Capability(
        "effect", "speed", CapabilityStatus.VERIFIED, _S32,
        "Speed is a real header field at byte offset 5 (APK_SECOND_PASS.md Q5(a)). MECHANISM "
        "CONFIRMED 2026-07-25 (vendor-app HCI capture, tools/parse_btsnoop.py): byte 5 IS how "
        "the app changes effect speed -- on gesture release it re-sends the WHOLE effect command "
        "[1c 00 03 02 style speed count + count*RGB] with a new byte 5, and never touches "
        "common.set_speed. HARDWARE-VERIFIED the same day (probes/probe_p1_followups.py group A, "
        "reference 32x32, operator-narrated): the app-exact frame at speed 100 / 5 / 100 ran "
        "SMOOTH / visibly SLOW / SMOOTH again, acked [05 00 03 02 01]. This overturns the "
        "2026-07-21 'no observable rate difference' reading (probes/probe_effect_speed{,2}.py, "
        "styles 2 and 4). Those probes went through our builder, which wrote a malformed length "
        "byte (6 + colorCount = 13 where the app sends 0x1c = the total frame length) -- the "
        "leading explanation for the device rendering the effect while apparently never reading "
        "the speed field. Builder fixed 2026-07-25; the length byte is NOT yet isolated as the "
        "cause (probe style/colors/method also differed) -- PROBE_PLAN P1-(c) runs the A/B.",
    ),
    Capability(
        "effect", "show_chunked", CapabilityStatus.KNOWN_BROKEN, _S32,
        "MutilColorAgreement.getSendData() bespoke [chunkLen+1, chunkIndex] 96/18-byte framing "
        "(APK_SECOND_PASS.md Q5(a)): both mtu variants ACKED but NO effect appeared on panel "
        "(probes/probe_capability_sweep3.py, 2026-07-21). The flat show() is the working path. "
        "CONFIRMED 2026-07-25 (vendor-app HCI capture, tools/parse_btsnoop.py): the app itself "
        "sends effects FLAT -- the captured frames start [1c 00 03 02 ...], a 28-byte complete "
        "command, never the [chunkLen+1, chunkIndex] sub-framing. Nothing on the wire justifies "
        "keeping the chunked variant beyond other-firmware parity. CANDIDATE EXPLANATION FOR THE "
        "INERT RESULT, found 2026-07-25: the flat command this builder slices carried the same "
        "malformed length byte effect.show did (6 + colorCount, not the total frame length), so "
        "the 2026-07-21 test re-assembled a malformed command on the device side. That byte is "
        "now fixed; the sub-header's own chunkLen+1 was CONFIRMED-FROM-SOURCE and is unchanged. "
        "Stays KNOWN_BROKEN -- the chunked path has not been re-sent to hardware since the fix.",
    ),
    Capability(
        "music_sync", "set_mic_type", CapabilityStatus.SOURCE_DERIVED, _S32,
        "BleProtocolN.setMicType; acked on hardware 2026-07-21 with no visible change of its "
        "own (probes/probe_capability_sweep3.py) -- effect unobservable in isolation. FRAME "
        "CORRECTED 2026-07-25 (vendor-app HCI capture, tools/parse_btsnoop.py): the frame is SIX "
        "bytes, [06 00 0b 80 mic_type value], observed [06 00 0b 80 01 64]. Our builder emitted "
        "five while declaring six, so every set_mic_type this SDK ever sent -- including the "
        "2026-07-21 hardware run -- was truncated, which voids the 'acked, no visible change' "
        "reading above. THE CORRECTED FRAME IS DEVICE-ACCEPTED, 2026-07-25 "
        "(probes/probe_p1_followups.py B2, reference 32x32): [06 00 0b 80 01 64] drew a POSITIVE "
        "ack (DeviceAck type=11 sub=128 accepted=True) where the old truncated frame could not "
        "have been well-formed, and it visibly SELECTS A DIFFERENT VISUALIZATION -- the identical "
        "rhythm-level stream renders one animation when sent cold and another after this frame "
        "(operator: 'mic mode animation appeared then again music mode. Both have separate "
        "animation'). Held at SOURCE_DERIVED rather than VERIFIED because what each mic_type "
        "VALUE selects is still unobserved: only type 1 has ever been sent.",
    ),
    Capability(
        "music_sync", "send_image_rhythm", CapabilityStatus.KNOWN_BROKEN, _S32,
        "BleProtocolN.sendImageRhythm promises a dancing figure; a 10-value stream was fully "
        "acked but NO figure appeared, and the clock face stuttered during the stream "
        "(probes/probe_capability_sweep3.py, 2026-07-21). REAL MECHANISM FOUND 2026-07-25 "
        "(vendor-app HCI capture, tools/parse_btsnoop.py): the app never sends this command for "
        "its music screen -- it streams rhythm LEVELS instead (see music_sync.rhythm_levels). "
        "This entry stays KNOWN_BROKEN: the command is still inert on our panel, and as of "
        "2026-07-25 the alternative is no longer hypothetical -- the rhythm-levels stream is "
        "hardware-verified to render (probes/probe_p1_followups.py group B), so this command has "
        "a working replacement and no remaining reason to be used.",
    ),
    Capability(
        "music_sync", "rhythm_levels", CapabilityStatus.VERIFIED, _S32,
        "protocol.music_sync.build_rhythm_levels, added 2026-07-25 from the vendor-app HCI "
        "capture (tools/parse_btsnoop.py): the PHONE does the FFT and streams [21 00 01 02 00] + "
        "16 level bytes to fa02 at ~10 Hz, unacked (byte 0 is a constant 0x21, not the 21-byte "
        "length). Observed levels 0x00-0x0d; the app mirrors 8 bands into a palindrome. "
        "HARDWARE-VERIFIED the same day (probes/probe_p1_followups.py group B, reference 32x32, "
        "operator-narrated): streamed from this SDK at a measured 10.0 Hz, 120 frames per phase. "
        "Cold from the clock with no mode entry it RENDERS ('music mode appeared but choppy'); "
        "after music_sync.set_mic_type's corrected frame the same stream renders a DIFFERENT "
        "animation ('mic mode animation appeared then again music mode. Both have separate "
        "animation'); a single static frame with all 16 levels at 0x0d rendered too ('mic mode "
        "again but really fast'). Silence proves nothing here -- the stream is unacked, so this "
        "is a visual result. STILL OPEN: the per-band -> pixel mapping (how many columns, which "
        "geometry, what 'full' means) was not readable from these phases.",
    ),
    Capability(
        "music_sync", "stop_rhythm", CapabilityStatus.SOURCE_DERIVED, _S32,
        "BleProtocolN.sendStopMicRhythm; acked 2026-07-21, nothing to observe stopping since "
        "send_image_rhythm never rendered (probes/probe_capability_sweep3.py).",
    ),
    # --- text ---
    Capability(
        "text", "show", CapabilityStatus.VERIFIED, _S32,
        "sendTextTo3232 port renders fully on a real 32x32; render A/B vs the generic packet "
        "2026-07-20 (ROADMAP.md section 3 Text).",
    ),
    Capability(
        "text", "show_generic_builder", CapabilityStatus.KNOWN_BROKEN, _S32,
        "The legacy/generic packet (build_text_packet, used when no screen_size is given) "
        "renders TRUNCATED on 32x32 -- 'HELLO' -> 'HEL' (A/B 2026-07-20); the earlier "
        "2026-07-19 'rejection' was a StatusAck SAVED misparse. Other panel sizes unprobed.",
    ),
    # --- gif ---
    Capability(
        "gif", "upload_file", CapabilityStatus.VERIFIED, _S32,
        "Chunked GIF upload with native playback, optimize=True required (FEATURE_MATRIX.md "
        "Display/rendering; ROADMAP.md section 3 Images). The old 'time_sign/ConvertTime "
        "semantics matched' claim was WRONG and is corrected 2026-07-25 (vendor-app HCI capture, "
        "tools/parse_btsnoop.py): the field is little-endian and the app's default key emits 5, "
        "where we wrote big-endian 10. Invisible until now because the client only ever uses the "
        "no-time-signature branch, which writes 00 00. The capture contained NO duplicate GIF "
        "upload, so the dedup/CRC-cache findings below remain ours alone. "
        "Ack semantics 2026-07-24 (probes/probe_gif_crc_cache.py): replies are StatusAck family "
        "(1,0). Status vocabulary UNIFIED with Timer/Schedule 2026-07-25 "
        "(probes/probe_gif_stored_chunk1.py): 1 = NEXT_CHUNK, 3 = SAVED, 0 = FAILED -- terminal "
        "semantics are no longer 'unresolved' (the earlier terminal-0-means-fresh-store reading "
        "was a misread of silent failures). Recognition is SINGLE-SLOT (device knows only the "
        "currently stored gif's CRC): chunk 1 of the stored gif SWITCHES PLAYBACK in ~1s with no "
        "artifacts (2026-07-25) -- a verified instant-takeover primitive, exposed as "
        "gif.activate_stored(). CHUNK-2 RACE proven visually 2026-07-25 "
        "(probes/probe_gif_color_reliability.py, tinted RED/GREEN/BLUE/YELLOW fixtures): ALL "
        "failures ever observed died at the chunk-2 position (+1.6-2.0s) -- RED and BLUE were "
        "silently doomed and left the previously stored color playing, while GREEN and YELLOW "
        "saved (terminal 3). Blind back-to-back sending hit ~50% silent failure on this panel "
        "(2 of 4). The SDK now PACES on the status handshake as of 2026-07-25 "
        "(client.py _send_gif_upload): send a chunk, await its StatusAck, restart the whole "
        "upload once on a doomed/timed-out pass -- the vendor app's own remedy for the race.",
    ),
    # --- common (device control) ---
    Capability(
        "common", "set_brightness", CapabilityStatus.VERIFIED, _S32,
        "5-100% works; out-of-range values nacked by the device via fa03 "
        "(ROADMAP.md section 3 Device).",
    ),
    Capability(
        "common", "set_power", CapabilityStatus.VERIFIED, _S32,
        "Power on/off exercised live (ROADMAP.md section 3 Device).",
    ),
    Capability(
        "common", "set_time", CapabilityStatus.VERIFIED, _S32,
        "RTC sync; alarms armed against it fired at the intended wall-clock time 2026-07-12. "
        "Stronger 2026-07-21: the RTC's WEEKDAY follows set_time too -- spoofing tomorrow's "
        "date flipped a day-masked timer from firing to silent (probes/probe_timer_weekbit.py). "
        "UNPARSED REPLY 2026-07-25 (vendor-app HCI capture, tools/parse_btsnoop.py): the app's "
        "set_time drew a NINE-byte notification, [09 00 01 80 04 0f 01 03 00] -- not the 5-byte "
        "ack shape. protocol/response.py requires len == 5 and returns None for it, which is "
        "correct and deliberately unchanged; documented here so the frame's existence is on "
        "record. Its payload (a device/firmware descriptor?) is undecoded.",
    ),
    Capability(
        "common", "device_id_read", CapabilityStatus.SOURCE_DERIVED, _S32,
        "The device exposes a readable ID string at ATT handle 0x0007: our panel returned "
        "\"TR2306R007-15\" to the vendor app (vendor-app HCI capture 2026-07-25, "
        "tools/parse_btsnoop.py). No SDK method reads it yet; recorded so a future model/firmware "
        "identification feature has a starting point. Handle numbers are per-connection GATT "
        "artifacts -- rediscover by UUID rather than hardcoding 0x0007.",
    ),
    Capability(
        "common", "set_screen_flipped", CapabilityStatus.VERIFIED, _S32,
        "Clock rendered upside down on True and righted on False "
        "(probes/probe_capability_sweep2.py, 2026-07-20). Full semantics 2026-07-24 "
        "(probes/probe_p8_geometry.py): flip is a 180-degree ROTATION applied at render time "
        "to everything -- DIY frames, graffiti, and native modes alike; command coordinates "
        "always stay in canonical unflipped space.",
    ),
    Capability(
        "common", "freeze_screen", CapabilityStatus.KNOWN_BROKEN, _S32,
        "Acked but NO observable effect in three tests 2026-07-20/21: didn't stop a running "
        "effect animation, didn't block graffiti draws from landing, no visual change on the "
        "clock; sending it again toggled nothing (probes/probe_capability_sweep{1,2}.py). "
        "Whatever setScreenFreeze controls, it is not visible on our panel.",
    ),
    Capability(
        "common", "set_speed", CapabilityStatus.KNOWN_BROKEN, _S32,
        "Acked but NO effect in two contexts: live text (A/B 2026-07-20 -- the text packet's "
        "own speed byte governs marquee smoothness) and a running effect (5/100/50 sweep "
        "mid-animation, probes/probe_effect_set_speed.py, 2026-07-21). The vendor app's "
        "effect-screen speed dial DOES change animation speed live (operator-confirmed, same "
        "panel), so real speed control rides an unmapped wire path -- HCI-snoop the app "
        "(ROADMAP M3 remaining). Calibration: our effect commands run at roughly the app "
        "dial's 50-60%; the app's 100% is visibly faster than anything we can send. RESOLVED "
        "2026-07-25 (vendor-app HCI capture, tools/parse_btsnoop.py): the app NEVER sends this "
        "frame -- not once across the whole scripted capture, speed dial included, so the vendor "
        "app never emits it at all. It is dead code in the vendor ecosystem. The speed dial "
        "re-sends the complete effect command with a new byte 5 instead, and that path is now "
        "hardware-verified on our own panel (effect.speed, VERIFIED 2026-07-25, "
        "probes/probe_p1_followups.py group A). Our byte layout is fine; there is simply nothing "
        "on the other end listening. Stays KNOWN_BROKEN: use effect byte 5 for effect speed and "
        "the text packet's own speed byte for marquee speed -- this command has no known use.",
    ),
    Capability(
        "common", "set_joint", CapabilityStatus.UNKNOWN, None,
        "Bytes match BleProtocolN.sendJoint, but the feature's purpose is unknown upstream too "
        "(FEATURE_MATRIX.md Device control; ROADMAP.md section 3 Display).",
    ),
    Capability(
        "common", "set_password", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.setPwd; byte-4 mode field hardcoded 1, unexplored (ROADMAP.md section 5). "
        "NEVER sent to hardware: the set/verify password probe is sequenced last across the "
        "roadmap by maintainer ruling 2026-07-20 -- lockout risk (ROADMAP.md section 17, SDK-M3).",
    ),
    Capability(
        "common", "verify_password", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.verifyPwd bytes confirmed (APK_PROTOCOL_FINDINGS.md section 1); ack shape "
        "unobserved and its (5,2) key collides with graffiti's nack (APK_SECOND_PASS.md Q4). "
        "Untested by the same maintainer ruling as set_password (ROADMAP.md section 17).",
    ),
    Capability(
        "common", "set_screen_timeout", CapabilityStatus.KNOWN_BROKEN, _S32,
        "No fa03 ack and no visual effect on our 32x32 (probes/probe_screen_timeout.py, "
        "2026-07-12) -- likely model-specific; units unknown pending a supporting model "
        "(ROADMAP.md sections 3 and 9).",
    ),
    Capability(
        "common", "read_screen_timeout", CapabilityStatus.KNOWN_BROKEN, _S32,
        "Same probe as set_screen_timeout: the screen-timeout family is unsupported on our "
        "32x32 (probes/probe_screen_timeout.py, 2026-07-12).",
    ),
    Capability(
        "common", "reset", CapabilityStatus.VERIFIED, _S32,
        "Used live 2026-07-18 to clear a stuck state (ROADMAP.md section 3 Device).",
    ),
    # --- experimental ---
    Capability(
        "experimental", "set_time_indicator", CapabilityStatus.KNOWN_BROKEN, _S32,
        "BleProtocolN.setTimeIndicatorEnable (FEATURE_MATRIX.md, findings section 2): acked on/"
        "off with NOTHING visible on the clock face (probes/probe_capability_sweep3.py, "
        "2026-07-21) -- matches the original lab's 'doesn't seem to work' report.",
    ),
    Capability(
        "experimental", "delete_device_data", CapabilityStatus.SOURCE_DERIVED, None,
        "Agreement.deleteDeviceMaterial, byte-identical across APK versions (FEATURE_MATRIX.md, "
        "findings section 3); destructive, never sent to hardware; requires confirm=True.",
    ),
    Capability(
        "experimental", "schedule_master_switch", CapabilityStatus.SOURCE_DERIVED, _S32,
        "All 4 packed enable/buzzer values accepted by hardware but bit semantics untested -- "
        "acks confirm receipt, not effect (probes/probe_schedule_master_switch.py; "
        "ROADMAP.md section 3 Alarms).",
    ),
    Capability(
        "experimental", "timer_close", CapabilityStatus.SOURCE_DERIVED, _S32,
        "Sent to hardware, but the ack is a state echo (statuses 0/1/3 observed from different "
        "states), so the disarm effect is unconfirmed (probes/probe_timer_close.py; "
        "ROADMAP.md section 3 Alarms).",
    ),
    Capability(
        "experimental", "timer_set", CapabilityStatus.VERIFIED, _S32,
        "Chunked handshake proven; GIF content fired animated with buzzer (2026-07-12; "
        "ROADMAP.md section 3 Alarms; ALARM_BUZZER_APK_FINDINGS.md). CONTENT_IMAGE SOLVED "
        "2026-07-21: it wants an encoded PNG bytestream, which fired and RENDERED at alarm "
        "time (probes/probe_content_image_and_recolor.py); raw RGB was SAVED but never "
        "rendered (2026-07-12). Text content unmapped (textSolve offsets untrustworthy in "
        "the decompile). Week bitmask VERIFIED 2026-07-21 via RTC spoofing "
        "(probes/probe_timer_weekbit.py): bit(d+1) for weekday d (Monday=0), bit0=enable; "
        "today-bit fired on the real day, went silent with the RTC spoofed to tomorrow, and "
        "tomorrow's bit fired under the spoof -- fire -> silence -> fire, mask evaluated "
        "against the device RTC weekday. Fire signature: buzzer first, content ~1-2s later.",
    ),
    Capability(
        "experimental", "schedule_set_theme", CapabilityStatus.VERIFIED, _S32,
        "GIF theme upload SAVED and fired inside its window 2026-07-12 -- end boundary looked "
        "minute-exclusive (probes/probe_schedule_gif.py; ROADMAP.md section 3 Alarms). Image "
        "content is PNG, not raw RGB (APK_SECOND_PASS.md Q2), and its on-device rendering plus "
        "the week-bit day mapping remain unverified.",
    ),
)

CAPABILITIES: Mapping[str, Capability] = MappingProxyType(
    {entry.name: entry for entry in _ENTRIES}
)
"""Read-only mapping of "feature.command" -> Capability."""


def capability(name: str) -> Capability:
    """Looks up one capability entry by its "feature.command" name.

    Raises KeyError (listing the known names) for anything not in the table --
    absence means "not yet inventoried", not "unsupported".
    """
    try:
        return CAPABILITIES[name]
    except KeyError:
        known = ", ".join(sorted(CAPABILITIES))
        raise KeyError(f"no capability entry named {name!r}; known entries: {known}") from None
