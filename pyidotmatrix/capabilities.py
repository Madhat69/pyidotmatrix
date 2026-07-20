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
        "ack-as-flow-control (ROADMAP.md section 3 Display; FEATURE_MATRIX.md Display/rendering).",
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
        "chronograph", "set_mode", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.setSecondChronograph (FEATURE_MATRIX.md Time-based); "
        "ROADMAP.md section 3: source-confirmed, never hardware-A/B'd.",
    ),
    Capability(
        "countdown", "set_mode", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.setCountDown (FEATURE_MATRIX.md Time-based); "
        "ROADMAP.md section 3: source-confirmed, runs autonomously on device.",
    ),
    Capability(
        "clock", "show", CapabilityStatus.VERIFIED, _S32,
        "Clock ticks on RTC through disconnects; not flash-persisted (persistence probes "
        "2026-07-17; 3-run clock probe 2026-07-19; ROADMAP.md section 3 Native modes).",
    ),
    Capability(
        "scoreboard", "show", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.setScoreboard (FEATURE_MATRIX.md Time-based); "
        "ROADMAP.md section 3: source-confirmed only.",
    ),
    Capability(
        "eco", "set_mode", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.setEco (FEATURE_MATRIX.md Device control); "
        "ROADMAP.md section 3: source-confirmed only.",
    ),
    Capability(
        "color", "show", CapabilityStatus.VERIFIED, _S32,
        "Fullscreen color flash-persists across power-cycle -- survived 3 days, 2026-07 "
        "(persistence probes 2026-07-17; ROADMAP.md section 3 Display).",
    ),
    Capability(
        "graffiti", "set_pixels", CapabilityStatus.VERIFIED, _S32,
        "Hardware-verified delta-render path; genuinely ack-silent, so the transport never "
        "awaits an ack for it (ROADMAP.md section 3 Display; FEATURE_MATRIX.md).",
    ),
    Capability(
        "graffiti", "mirror", CapabilityStatus.UNKNOWN, _S32,
        "Byte-3 values 0/1/2/4 render identically, 3 is nacked [5,0,5,2,0] (probe 2026-07-12; "
        "probes/probe_graffiti_mirror.py); no counterpart in the current app's own send path "
        "(APK_SECOND_PASS.md Q5(c)) -- treated as a firmware quirk.",
    ),
    Capability(
        "effect", "show", CapabilityStatus.VERIFIED, _S32,
        "Effect mode activated live with the historical speed=90 during persistence probes "
        "2026-07-17 (ROADMAP.md section 3); header layout confirmed from "
        "MutilColorAgreement.java:42-72 (APK_SECOND_PASS.md Q5(a)).",
    ),
    Capability(
        "effect", "speed", CapabilityStatus.SOURCE_DERIVED, None,
        "Speed is a real header field at byte offset 5 (APK_SECOND_PASS.md Q5(a)); this SDK has "
        "only ever sent 90 to hardware, so other values are source-derived.",
    ),
    Capability(
        "effect", "show_chunked", CapabilityStatus.SOURCE_DERIVED, None,
        "MutilColorAgreement.getSendData() bespoke [chunkLen+1, chunkIndex] 96/18-byte framing "
        "(APK_SECOND_PASS.md Q5(a)); never sent to hardware by this SDK.",
    ),
    Capability(
        "music_sync", "set_mic_type", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.setMicType (FEATURE_MATRIX.md Audio/sensor); kept for parity, never "
        "hardware-exercised (ROADMAP.md section 3 Native modes).",
    ),
    Capability(
        "music_sync", "send_image_rhythm", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.sendImageRhythm (FEATURE_MATRIX.md Audio/sensor); never hardware-exercised.",
    ),
    Capability(
        "music_sync", "stop_rhythm", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.sendStopMicRhythm (FEATURE_MATRIX.md Audio/sensor); never hardware-exercised.",
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
        "Chunked GIF upload with native playback, optimize=True required; time_sign/ConvertTime "
        "semantics matched (FEATURE_MATRIX.md Display/rendering; ROADMAP.md section 3 Images).",
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
        "RTC sync; alarms armed against it fired at the intended wall-clock time 2026-07-12 "
        "(ROADMAP.md section 3 Device and Alarms).",
    ),
    Capability(
        "common", "set_screen_flipped", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.setRotate180 (FEATURE_MATRIX.md); ROADMAP.md section 3: source-confirmed, "
        "unverified on our panel.",
    ),
    Capability(
        "common", "freeze_screen", CapabilityStatus.SOURCE_DERIVED, None,
        "Lab-ported, matches the app's overall pattern (FEATURE_MATRIX.md Device control); "
        "ROADMAP.md section 3: source-confirmed only.",
    ),
    Capability(
        "common", "set_speed", CapabilityStatus.KNOWN_BROKEN, _S32,
        "Acked but had NO effect on live text -- the text packet's own speed byte governs "
        "marquee smoothness instead (text A/B 2026-07-20, ROADMAP.md section 3 Text). Effect on "
        "other modes untested.",
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
        "experimental", "set_time_indicator", CapabilityStatus.SOURCE_DERIVED, None,
        "BleProtocolN.setTimeIndicatorEnable, bytes still shipped by the current app "
        "(FEATURE_MATRIX.md, findings section 2); original lab reported 'doesn't seem to work' "
        "on some models; unverified on our panel.",
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
        "Chunked handshake proven; GIF content fired animated with buzzer, and raw-RGB image "
        "content renders after the little-endian header fix (2026-07-12; ROADMAP.md section 3 "
        "Alarms; ALARM_BUZZER_APK_FINDINGS.md). Text content unmapped (textSolve offsets "
        "untrustworthy in the decompile). Week bitmask: Sunday bit confirmed live, full day "
        "mapping unverified.",
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
