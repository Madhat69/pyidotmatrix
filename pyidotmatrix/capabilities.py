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
        "path is unaffected. DIY PERSISTENCE CONFIRMED VOLATILE ACROSS A BLE RECONNECT "
        "2026-07-27 (P11 persistence matrix, see display.persistence_matrix): a DIY frame "
        "resets to the clock on reconnect, validating the client's existing assumption that "
        "device-side DIY state does not survive a reconnect. CORRECTION: the matching "
        "software-power-cycle cell from that same run is VOID, not a second confirmation -- a "
        "methodology flaw left the row's state unarmed going into that interruption (see "
        "display.persistence_matrix); do not cite the software power cycle as independently "
        "measured for this row. SUSTAINED-RATE ENVELOPE MEASURED 2026-07-28 (P4, probes/"
        "probe_p4_streaming_endurance.py): unacked full frames paced at 1.5 fps held for 600 s "
        "-- 900 frames, 900 acks, ack:frame 1.00, 1.50/s achieved against a 1.50/s target, zero "
        "missed pacing slots, zero reconnects, no write failures, no throughput decay across the "
        "full ten minutes. The safe sustained full-frame envelope therefore sits just under the "
        "~1.75 fps render cap measured above. *** MIXED-MODE STREAMING COSTS ~27% OF THE FRAME "
        "ACKS *** same run: interleaving graffiti deltas with full frames (300 frames + 2999 "
        "deltas over 300 s at 11.00/s, exact pacing, no reconnects) returned only 218 acks for "
        "300 frames -- ack:frame 0.73 against 1.00 for frames alone, corroborated by 0.87 in a "
        "15 s smoke run. Since the fa03 ack is the device's frame-processed signal and the SDK's "
        "free flow control, a caller pacing a delta stream with periodic keyframes gets "
        "materially fewer acks to pace on than pure full-frame mode would give it. The mechanism "
        "is UNKNOWN; this is the measurement and its consequence, not an explanation.",
    ),
    Capability(
        "display", "write_without_response", CapabilityStatus.VERIFIED, _S32,
        "fa02 advertises write-without-response and our panel honors it: unacked frames "
        "rendered on-screen during the 2026-07-20 streaming benchmark (operator-observed). "
        "Firmware-variant caveat: LumiSync's RE notes report no-response writes IGNORED on "
        "their unit, while idotmatrix-overclocked uses them successfully on a 64x64 -- treat "
        "as per-variant. Sustained flooding eventually dropped our BLE link twice; pace near "
        "the ~1.75 fps render cap. PACKET RE-SPLITTING VALIDATED 2026-07-27 (P9, probes/"
        "probe_p9_write_boundaries.py): the same landmark DIY frame, hopping GIF and "
        "scrolling-text payloads were sent at forced write sizes 18, 20, 128 and the link's "
        "negotiated 514 bytes -- ALL FOUR rendered identically and correctly, including the "
        "trailing bottom-right pixel that a dropped final packet would darken. "
        "transport.write_packets' re-splitting is therefore measured correct down to 18 "
        "bytes per write, and the BlueZ low-MTU escape hatch (write_size_override) is safe "
        "to recommend for panels this SDK cannot test directly. WRITE-MODE THROUGHPUT, same "
        "probe: an identical frame at the negotiated write size took 0.67s with "
        "response=True (final packet GATT-acked) vs 0.11s with response=False -- unacked "
        "writes ran 3-6x faster across the sizes measured, with no rendering difference "
        "either way. PACING, NOT THE WRITE MODE, IS WHAT KEEPS THE LINK ALIVE 2026-07-28 (P4, "
        "probes/probe_p4_streaming_endurance.py): 900 unacked full frames paced at 1.5 fps ran "
        "600 s with zero reconnects, and 255-px unacked graffiti deltas held 40 cmd/s cleanly -- "
        "so the two link deaths above belong to flooding, not to write-without-response itself. "
        "See display.show_frame and display.set_pixels for the measured envelopes.",
    ),
    Capability(
        "display", "set_pixels", CapabilityStatus.VERIFIED, _S32,
        "Graffiti delta path, ~20 ms unacked, <=255 px/command "
        "(ROADMAP.md section 3 Display; FEATURE_MATRIX.md Display/rendering). The 255 cap is "
        "a HARD SAFETY LIMIT: 256 pixels in one command crashes the panel's BLE stack and "
        "needs a physical power cycle (P13 phase E, 2026-07-25 -- see graffiti.set_pixels). "
        "This method batches, so it is safe. SUSTAINED DELTA CEILING MEASURED 2026-07-28 (P4, "
        "probes/probe_p4_streaming_endurance.py, 255-px commands through this method): 10, 20 "
        "and 40 cmd/s each ran for 30 s at exactly their target with ZERO missed pacing slots "
        "and no reconnects; 60 cmd/s achieved only 55.23/s and dropped 143 pacing slots, which "
        "is unambiguous back-pressure even though the probe's own RATE_COLLAPSE criterion (0.75 "
        "of target) did not fire. 40 cmd/s is the safe figure to design against and ~55/s is the "
        "observed hard ceiling -- consistent with the ~20 ms per command above (~50/s "
        "theoretical). Interleaving these deltas with full frames costs frame acks; see "
        "display.show_frame.",
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
    Capability(
        "display", "persistence_matrix", CapabilityStatus.VERIFIED, _S32,
        "P11 PERSISTENCE MATRIX, automated columns 2026-07-27 (probes/probe_p11_"
        "persistence.py): every row tested (clock, DIY frame, fullscreen colour, GIF, text, "
        "effect, flip, brightness, eco, power) against a BLE disconnect/reconnect (~6s), and "
        "then a software power off/on (~5s) cycle chained onto whatever the first interruption "
        "left in force. READ EVERY CELL BELOW AS A PROTECTED RESULT: the sweep runs its rows "
        "in sequence, so from the second row onwards each state was armed AFTER an earlier "
        "disconnect/reconnect in the same process -- condition (B) of the LAZY DISPLAY-STATE "
        "PERSISTENCE model recorded further down. 'GIF held' here and 'GIF died' there are both "
        "true and are not in tension -- this matrix measures durability once a row is already "
        "protected, and nothing else. The clock control row is additionally VACUOUS as a "
        "durability test: a clock face dying back to the clock face is "
        "undetectable. ONLY THE DIY FRAME IS VOLATILE ON THE BLE-RECONNECT COLUMN -- it resets "
        "to the clock there; every native mode (fullscreen colour, GIF, text, effect, flip, "
        "brightness, eco) HELD. CORRECTION, methodology flaw found on review: the DIY row's "
        "software-power-cycle CELL IS VOID, not a second confirmation. The run establishes each "
        "row's state ONCE, then runs the BLE interruption, then runs the software-power "
        "interruption WITHOUT re-arming the state in between (probes/probe_p11_persistence.py, "
        "the row loop from ~line 580). For every other row that is a valid chained test, because "
        "the state survived the first interruption and was still there to be power-cycled. For "
        "DIY it is not: DIY already lost to the BLE reconnect, so the power-cycle cell only "
        "re-observed the clock the first interruption had already produced. The matrix is NOT "
        "trusted wholesale on this account -- the void cell needs a re-run with DIY's state "
        "re-established between the two interruptions before it can be marked either way. "
        "Cross-validates two other findings from the same session: brightness persisting "
        "matches common.set_brightness's 'persists until the next brightness command'; eco "
        "persisting matches eco.set_mode's 'autonomous device state'. CORRECTED CROSS-"
        "REFERENCE to P12 (probes/probe_p12_mode_state_machine.py, full five-sequence result -- "
        "see display.invalidate_diy_mode): DIY dying here is NOT explained by 'DIY re-entry is "
        "required after a software power off/on' as a blanket rule -- a clean P12 sequence-5 "
        "rerun with nothing sent while the panel was dark found the DIY frame SURVIVED the "
        "power cycle and NO re-entry was needed; the earlier GREEN-only result traced to a "
        "scoreboard command sent (invisibly, screen off) during the dark window, which left a "
        "native mode live at power-on and forced the reclaim. The real model is whether a "
        "native mode is actively live, not the power cycle itself; see display."
        "invalidate_diy_mode for the full finding. GLANCEOS CONSEQUENCE: after a BLE reconnect "
        "the panel shows the CLOCK and the caller MUST re-push a frame -- no native mode covers "
        "for it, which is the rationale for a 60s keyframe and a reconnect watchdog; whether a "
        "bare software power cycle carries the same consequence is unresolved pending the void "
        "cell's re-run. STILL OPEN: the PHYSICAL power-cycle column (pulling mains power at the "
        "wall) is NOT covered by this result for this matrix's rows -- P6's Q4 physical "
        "power-cycle exercised Timer alarms only; queued in docs/PROBE_PLAN.md. LAZY "
        "DISPLAY-STATE PERSISTENCE, THE CORRECTED MODEL, 2026-07-28 -- THIS SUPERSEDES AND "
        "RETRACTS 'THE FIRST-CONNECTION SHADOW'. This entry twice named a novel phenomenon for "
        "what is an ALREADY-RECORDED PROPERTY OF THIS PANEL: first a 'reset shadow' blamed on "
        "common.reset(), then a 'first-connection shadow' scoped to the client session. Both "
        "framings are DISPROVEN and neither is to be repeated. PRIOR ART, in this lab's own "
        "record, cited so it cannot be rediscovered a third time: 2026-07-12 -- 'the device "
        "persists its current native mode to flash LAZILY (dwell somewhere under ~3 min) and "
        "boots into the last persisted mode'; 2026-07-17 -- 'CLEAN BLE disconnect -> device exits "
        "DIY -> reverts to the persisted screen in ~2s'. Those two together account for nearly "
        "everything the shadow series observed; the session-scoped framing was an artifact of "
        "UNCONTROLLED ELAPSED TIME between commands (the operator typing between runs), which was "
        "not held constant until the very last probe. THREE DISTINCT DEVICE STATES, PREVIOUSLY "
        "CONFLATED -- separate these before reading anything below, because treating them as one "
        "was the single largest source of confusion in the whole series. (1) THE GIF STORAGE "
        "SLOT: survives a BLE reconnect AND a power cycle -- seed-215 was still recognised "
        "(status 3) after a mains power cycle. (2) THE ACTIVE DISPLAY MODE: reasserts on a "
        "reconnect, and is cleared by a power cycle. (3) THE FLASH / BOOT DISPLAY STATE: what the "
        "panel boots into, and NOT what a reconnect restores. All three were seen to DISAGREE at "
        "the same moment, 2026-07-28: after a power cycle the panel booted STRAIGHT TO ORANGE "
        "with no noise flash, while the GIF slot still held seed-215 and a BLE reconnect minutes "
        "earlier had reverted to NOISE. Boot state, revert target and stored payload were three "
        "different things simultaneously. THIS RECONCILES the two readings that looked "
        "contradictory all week: color.show's 'fullscreen colour flash-persisted for 3 days' "
        "(2026-07-17) is BOOT state, and 'colour dies on reconnects' (2026-07-28) is the ACTIVE "
        "mode reasserting. They were never in conflict, and neither needs softening. THE MODEL: "
        "display-mode state -- which "
        "content the panel is showing -- lives in RAM when first written and is committed to "
        "flash LAZILY, and a clean BLE disconnect makes the device revert to its LAST PERSISTED "
        "mode. Content written and then disconnected-from too quickly is therefore lost and the "
        "panel comes back on whatever was persisted, usually the clock. It renders, it acks "
        "normally (StatusAck status=3, SAVED), and it goes silently, with no error raised "
        "anywhere in the stack. CONTENT SURVIVES A DISCONNECT/RECONNECT IF EITHER OF TWO "
        "INDEPENDENT SUFFICIENT CONDITIONS HOLDS; neither is necessary. (A) DWELL -- ENOUGH TIME "
        "HAS PASSED SINCE THE WRITE, in a session with NO PRIOR RECONNECT. THRESHOLD BRACKETED "
        "2026-07-28 AT 100 s < t <= 180 s by a dwell ladder, run one trial per invocation on "
        "probes/probe_p19_g5_kill_event.py `own-delayed <seconds>` (the same session performs "
        "both the write and the reconnect, so session identity is held constant and only the "
        "dwell varies): 8, 30, 60, 75, 90 and 100 s ALL DIED; 180 s SURVIVED. Every death in the "
        "ladder was a first-connection session with no prior reconnect. This CONFIRMS the "
        "2026-07-12 record's 'dwell somewhere under ~3 min', which was right all along. NARROWING "
        "THE 100-180 s BAND IS DELIBERATELY NOT WORTH MORE PANEL TIME: a valid isolated trial "
        "costs ~6 minutes (see the PROTOCOL RULE below) and the integrator guidance -- allow ~3 "
        "minutes, or reconnect once first -- does not change anywhere inside that band. (B) A PRIOR "
        "DISCONNECT/RECONNECT EARLIER IN THE SAME SESSION. `--preamble ble gif` survives a "
        "reconnect only ~8 s after the upload, REPRODUCED TWICE (2026-07-27 and 2026-07-28), and "
        "on the 07-28 run the operator reported the animation CONTINUED FROM WHERE IT WAS rather "
        "than restarting -- the device did not re-initialise playback at all, it ran straight "
        "through the disconnect. The matched control `--no-reset gif` (no preamble, same ~8 s) "
        "reliably DIES. DWELL CANNOT EXPLAIN THIS: same 8 s, opposite outcome. The "
        "prior-reconnect rescue is a REAL, SEPARATE effect. ITS MECHANISM IS NOW KNOWN "
        "2026-07-28 (P19 G8, probes/probe_p19_g8_commit_arming.py): **A PRIOR RECONNECT ARMS "
        "THE FLASH COMMIT.** BLUE written 8 s after a reconnect, against a flash state still "
        "holding G7's green, BOOTED BLUE after a physical power cycle -- an 8-second-old write "
        "reached FLASH where (A) alone needs 100-180 s, and blue had no dwell of its own, which "
        "excludes the alternative G7 left open (that G7's green had merely committed during the "
        "~28 s it happened to be up). So (B) is a COMMIT mechanism, not a display quirk: "
        "(A) unassisted = lazy commit at 100-180 s; (B) after a reconnect = commit armed, <=8 s. "
        "That run also caught the revert in the act TWICE, the panel falling back to green after "
        "BOTH connection events before blue was written, independently confirming green was "
        "committed rather than lingering. GLANCEOS: this EXPLAINS the daemon's double-tap "
        "connect rather than merely justifying it empirically -- every session it opens is in "
        "(B), so what it writes commits promptly instead of waiting out a timer it would rarely "
        "survive. (B) IS NOT "
        "GIF-SPECIFIC AND IS DURABLE ALMOST IMMEDIATELY -- EXTENDED TO FULLSCREEN COLOUR "
        "2026-07-28 (P19 G7, probes/probe_p19_g7_isolated_dwell.py): green written 10 s after a "
        "reconnect SURVIVED, where 10 s in a first-connection session sits well inside the six "
        "consecutive deaths of the (A) ladder. ~10 s of (B) beats 100 s of (A). EVIDENCE, "
        "every relevant run -- this table is the whole basis of the model: `gif` x2 (no prior "
        "reconnect, ~8 s) DIED; `--delay 120 gif` (no prior reconnect, ~8 s -- the 120 s ran "
        "BEFORE the write) DIED; `--no-reset gif` x2 (no prior reconnect, ~8 s) DIED; "
        "`--no-reset color` (no prior reconnect, ~8 s) DIED; `--preamble power gif` (power blink "
        "only over the same link, so no prior reconnect, ~8 s) DIED; `--preamble ble gif` x2 "
        "(PRIOR RECONNECT, ~8 s) SURVIVED, animation continued; `clock gif` and the full row "
        "sweep (prior reconnect supplied by the preceding row, ~8 s) SURVIVED; the `g5 "
        "own-delayed` DWELL LADDER (fullscreen colour, no prior reconnect, one trial per "
        "invocation) DIED at 8, 30, 60, 75, 90 and 100 s and SURVIVED at 180 s; `g7 trial` "
        "(fullscreen colour, PRIOR RECONNECT, 10 s dwell, against a decoy that was verified "
        "distinct) SURVIVED; `g5 reconnect` (foreign "
        "session, minutes of dwell) SURVIVED; `set brightness` followed by a PHYSICAL mains power "
        "cut (minutes) SURVIVED, the panel booted to it. RETRACTED RUNS -- DO NOT COUNT THESE AS "
        "EVIDENCE, in either direction: `own-delayed 140` (SURVIVED) and the `own-delayed 60` "
        "RERUN (SURVIVED) both wrote ORANGE while orange was ALREADY the flash state, so "
        "reversion and survival were the same picture and neither run could discriminate. The 60 "
        "s rerun was the worse of the two -- it activated a noise GIF as a decoy but gave it only "
        "~10 s, nowhere near a commit, so flash still held orange underneath. THE EARLIER '90 s "
        "SURVIVED' READING IS WITHDRAWN FOR THE SAME REASON, and it is the one that first sent "
        "the model astray; the ladder's 90 s point, run under a valid discriminator, DIED. RULED "
        "OUT as the operative variable: "
        "common.reset() (`--no-reset` died identically, twice, re-run with no variables changed "
        "and reproduced exactly); a device power blink over the same link (`--preamble power` "
        "died, so no cheap power-blink mitigation exists); elapsed time BEFORE the write "
        "(`--delay 120` died); GIF-SPECIFIC MACHINERY (`--no-reset color` carries no payload at "
        "all and died the same way, so what is lost is the CURRENT-MODE POINTER, broadly across "
        "display state); and SESSION IDENTITY, retracted next. RETRACTED -- THE "
        "PER-CLIENT-SESSION CLAIM, previously recorded here as G1b 'strictly per-client-session, "
        "confirmed twice'. It rested on foreign sessions failing to kill content they had not "
        "written. Those runs ALL had minutes of elapsed time, so they satisfied condition (A) and "
        "prove NOTHING about session identity; the dwell ladder's 180 s point then showed the "
        "SAME session failing to kill its own 180-second-old content. (This retraction was "
        "originally rested on a 90 s run that is now itself withdrawn as flash-confounded; the "
        "180 s ladder point carries it instead, so the conclusion is unchanged but its evidence "
        "has been re-anchored.) Session identity is not the variable and "
        "no part of this model is scoped to the client session, the transport instance, or the "
        "process. CONSEQUENCE FOR INTEGRATORS: multiple clients CAN share this panel, but the "
        "reason is DWELL, not ownership. METHODOLOGY, operator-caught and applied throughout: A "
        "DYING RUN YIELDS EXACTLY ONE MEASUREMENT. Once interruption 1 (the BLE reconnect) has "
        "killed the content, interruption 2 reads a clock that was already on screen -- that cell "
        "is VOID, the same flaw as the DIY row's above. Earlier 'clock after BOTH interruptions' "
        "phrasing overstated the evidence and is withdrawn, and the headline is narrowed from "
        "'lost at the next reconnect or power cycle' to LOST AT THE NEXT BLE RECONNECT. SCOPE "
        "LIMIT, DO NOT OVER-GENERALISE: this is NOT 'nothing survives a first connection'. "
        "ALARMS ARE UNAFFECTED -- P6's Q4 armed both alarm slots in their own process, therefore "
        "on a first connection, and after a PHYSICAL power cycle both fired with payloads intact "
        "(red+beep 12:34, blue 12:35; see experimental.timer_set). THE ORGANIZING MODEL, and the "
        "frame every other entry should reference rather than restate: CONFIG-CLASS device state "
        "(the RTC, alarms, schedules, brightness) and STORED PAYLOADS (GIF bytes in flash) commit "
        "durably and PROMPTLY on any connection; DISPLAY-CLASS state -- the current-mode pointer "
        "alone -- commits LAZILY, and it is the only thing at risk. BRIGHTNESS IS CONFIG-CLASS, "
        "SETTLED 2026-07-28 (P19 G1, "
        "`--no-reset brightness`, two runs; run 2 is the record): the row's baseline is a flat "
        "WHITE field at brightness 10, two variables on one screen. Operator: clock at full "
        "brightness -> WHITE, DIM (baseline) -> CLOCK, STILL DIM (after the BLE reconnect) -> full "
        "brightness at the probe's restore. The white field DIED at the reconnect, display-class "
        "as expected; THE DIMMING SURVIVED. Brightness therefore joins the CONFIG class with the "
        "RTC, alarms and schedules, and it separately survived a PHYSICAL MAINS POWER CUT (set "
        "brightness, plug pulled at the wall, panel booted glare -> boot animation -> dim white), "
        "so it is flash-backed outright. Note this run yields TWO VALID MEASUREMENTS rather than "
        "one: the void-second-column rule applies only to state interruption 1 had already "
        "killed, and brightness was still in force going into interruption 2, so brightness "
        "survived a BLE reconnect AND a software power cycle. CONSEQUENCE: pinning brightness "
        "once at startup is SAFE -- night-mode / startup-reassert designs need nothing to protect "
        "it. POINTER-NOT-PAYLOAD, CONFIRMED 2026-07-28 (P19 G2, `probe_p11_persistence.py "
        "shadow-recover` -- the MODE NAME is a legacy label from the retracted model, kept only "
        "because it is the probe's CLI handle; operator reading of all four steps: HOP -> CLOCK "
        "-> HOP -> HOP). A 4-corner-hop GIF uploaded as the session's FIRST command rendered; the "
        "BLE reconnect killed it back to the clock; gif.activate_stored() with the SAME bytes and "
        "NO RE-UPLOAD BROUGHT IT BACK -- the call returned True, so the device recognized its "
        "stored CRC and never asked for a re-transfer, and the animation actually RENDERED, which "
        "on this panel is the distinction that matters; and a further BLE reconnect, by then a "
        "session holding both a prior reconnect and dwell, left the hop up, proving the restore "
        "durable rather than transient. THE LOSS DESTROYS NOTHING: the stored payload commits to "
        "flash promptly and normally, and what is committed lazily is ONLY the device's "
        "current-mode pointer. SDK RECOVERY RULE, evidence-backed: RE-ACTIVATE, DO NOT "
        "RE-TRANSFER -- one small command instead of a full chunked upload (see gif.upload_file). "
        "SCOPE CAVEAT: demonstrated for stored GIFs, which HAVE an explicit re-activate path. It "
        "does not follow that other display-class content is recoverable the same way -- a parked "
        "DIY still (DIY-clear -> frame -> QUIT_STILL) has no 'activate what you already have' "
        "command, so that path has no equivalent recovery and must rely on dwell or a prior "
        "reconnect. ACTIVATING A STORED GIF DOES NOT COMMIT IT, 2026-07-28 (P19 G7, "
        "probes/probe_p19_g7_isolated_dwell.py, observed ONCE): the stored noise GIF was activated "
        "and held as the ACTIVE display for 200 s -- longer than the 180 s that committed orange "
        "in the (A) ladder -- and the verification reconnect showed ORANGE, not noise. Flash still "
        "held the previous trial's colour. So gif.activate_stored() switches PLAYBACK without "
        "arming whatever the commit path is, which is a fourth thing that must not be conflated "
        "with the three states above: making content VISIBLE is not the same as making it "
        "COMMITTED. Mechanism OPEN; recorded as observed, not explained. PROTOCOL RULE for any "
        "future durability trial, learned the hard way TWICE (see the retracted runs above): to "
        "ask 'did this write survive?', the PERSISTED state must differ from what is being "
        "written -- not merely the ACTIVE one -- and establishing that costs a full commit period "
        "of its own, so a VALID ISOLATED TRIAL IS ~6 MINUTES, not 2. G7 is the first trial run to "
        "that standard, and it stayed valid even though its own premise (the decoy committing) "
        "FAILED: green differed from BOTH candidate revert targets, orange (flash) and noise "
        "(active), so the reading was clean whichever would have won. CONSISTENT-WITH, from the "
        "older record: color.show's fullscreen colour survived THREE DAYS including power cycles "
        "(2026-07-17 persistence probes) -- pushed once and then left alone for days, so it was "
        "the BOOT/flash state by then (state 3 above), with condition (A) satisfied many times "
        "over. That is why it does not contradict colour dying on a short-dwell reconnect. "
        "MECHANISM OF THE PRIOR-RECONNECT RESCUE: OPEN, and the one genuinely unexplained piece "
        "left. The probe's reconnect calls "
        "client.disconnect() then client.connect() -- the SAME connect() used for the initial "
        "connection, and IDotMatrixClient.connect() only awaits BleTransport.connect() (no clock "
        "command, no set_time), so these are not two different client code paths. A read of "
        "transport/ble.py closes the last suspicion on our side: connect() does NOT branch on a "
        "cached BLEDevice -- discovery runs only when no MAC was given, the probe always passes "
        "one, and every call builds a fresh BleakClient and re-subscribes identically. Nothing "
        "in our stack distinguishes the two connections, so if anything does, the DEVICE does; an "
        "HCI capture comparing connection 1 with connection 2 is the definitive tool and is "
        "queued in docs/PROBE_PLAN.md. NO MITIGATION IS IMPLEMENTED IN THIS DRIVER, and the cheap "
        "one is off the table: `--preamble power` died, so the only two known protections are to "
        "let content DWELL (~3 minutes, per the ladder) or to perform a real throwaway "
        "connect/disconnect/reconnect (~10 s of protection afterwards is enough). For "
        "stored GIFs the cheaper answer is G2's recovery rule (re-activate, do not re-transfer) "
        "rather than either. GLANCEOS "
        "CONSEQUENCE: content pushed and then disconnected from within a few seconds is on a "
        "timer from the moment it is written, so a periodic keyframe is not an edge-case nicety "
        "-- it is what keeps the panel alive after any blip. Re-runs and the open questions are "
        "queued in docs/PROBE_PLAN.md P19.",
    ),
    Capability(
        "display", "invalidate_diy_mode", CapabilityStatus.VERIFIED, _S32,
        "P12 FULL RESULT 2026-07-27, all five sequences run (probes/probe_p12_mode_state_"
        "machine.py, rebuilt one-sequence-per-invocation after two unfollowable multi-sequence "
        "attempts). HEADLINE: the question is not 'does DIY mode need re-entry', it is "
        "'IS A NATIVE MODE STILL ACTIVELY DRAWING'. A show_frame() sent without "
        "invalidate_diy_mode() is NEVER rejected and NEVER swallowed at the protocol level -- it "
        "arrives, acks ACCEPTED, and RENDERS. Whether it then stays on screen depends on whether "
        "something else still owns the framebuffer. Per sequence: (1) after TEXT -- re-entry "
        "required, but not because the frame was dropped: the naive frame rendered (a red "
        "flicker was seen), then the still-running marquee scroll repainted over it on its next "
        "tick. The command lost a REPAINT RACE, not a silent swallow -- the long-standing "
        "'silently swallowed while acking ACCEPTED' description is corrected: swallowed is wrong, "
        "outraced is right, though the practical fix (call invalidate_diy_mode) is unchanged. "
        "(2) after CLOCK + GRAFFITI -- NO re-entry needed, naive frame held. Also (2)'s own "
        "result: graffiti sent onto a running native clock, no DIY mode, does NOT composite over "
        "it -- it forces a MODE SWITCH (operator: 'nothing drew over each other and the clock "
        "stayed for a sec and switched'). The daemon's delta-render assumption (graffiti is a "
        "safe overlay from any state) is therefore WRONG as a blanket claim: it is only a safe "
        "delta once the panel is ALREADY in the pixel/DIY framebuffer; sent while a native mode "
        "is showing, it forces a mode transition instead of drawing through. GlanceOS must push a "
        "full frame before it starts streaming graffiti deltas. Also noted in (2): a native clock "
        "does take over cleanly from a DIY frame, but only holds ~1s before the next command in "
        "the sequence lands. (3) after GIF + EFFECT -- re-entry required, with a distinctive "
        "footprint: the naive red frame appeared and was then visibly DRAGGED DOWN/PUSHED by the "
        "running rainbow effect, which consumed it into its own falling animation rather than "
        "simply overwriting it. THE EFFECT OPERATES ON THE LIVE FRAMEBUFFER, not a private buffer "
        "-- it transforms whatever pixels are already there. (4) after the TIMER BRANCH -- "
        "re-entry required, with a THIRD distinct footprint: the naive red frame stayed visible "
        "as a background while the chronograph's digits and dot animation drew over it (digits "
        "visibly changing on top of red) before the panel fully reverted. Native modes repaint "
        "only their OWN DIRTY REGIONS -- text takes the full width, the effect takes the whole "
        "buffer, the chronograph takes only its glyphs -- so the same 'was it swallowed' question "
        "has at least three different visual answers depending which mode is live. (5) after "
        "software POWER OFF/ON -- NO re-entry needed on a clean run (see display."
        "persistence_matrix for the correction to the earlier power-cycle framing; the original "
        "GREEN result traced to a scoreboard command executed invisibly while the screen was "
        "dark, which left a native mode live at power-on, not to the power cycle itself). ONE "
        "UNEXPLAINED TRANSIENT: a brief unreadable flicker between green and the clock at the "
        "end of sequence 4 -- logged, not theorised about; the third such unreproduced flicker "
        "this session (see display.visual_transients). SPECULATIVE, UNPROBED, NOT A CAPABILITY: "
        "sequence 3 raises the possibility that content could be deliberately FED to a running "
        "effect (write a frame, start the effect, watch it animate the caller's own pixels) -- "
        "queued as a follow-up in docs/PROBE_PLAN.md, not claimed here.",
    ),
    Capability(
        "display", "visual_transients", CapabilityStatus.UNKNOWN, _S32,
        "TWO OBSERVED-BUT-UNREPRODUCED visual glitches, logged rather than explained, because "
        "each occurred with the BLE link otherwise healthy. (1) 2026-07-24, single-chunk GIF "
        "sends (docs/PROBE_PLAN.md P2): a transient render glitch -- stutter, CRT-like "
        "artifacts, bottom-row pixels stuck orange-ish -- appeared once. It was chased through "
        "probe_gif_chunk1_isolation.py and probe_gif_stored_chunk1.py and never reproduced "
        "again, including on the specific recognized-chunk-1 case it was first suspected to be "
        "(P2d, 2026-07-25: that case switched playback cleanly, no artifacts); downgraded to an "
        "unexplained one-off but kept on record rather than discarded. (2) 2026-07-27, "
        "probes/probe_effect_speed_sweep.py: a one-off FREEZE at a single effect-to-scoreboard "
        "phase transition. The five (or more) other identical transitions in the same run were "
        "seamless, and the transport's scoreboard acks were spaced EVENLY at 14.44-14.61s "
        "across the event -- consistent, jitter-free timing that shows the BLE link did not "
        "stall; whatever froze the display did not freeze the link. Neither event has a "
        "reproduction recipe; both are recorded as a caution against reading a single glitchy "
        "run as evidence of a protocol bug.",
    ),
    # --- native modes ---
    Capability(
        "chronograph", "set_mode", CapabilityStatus.VERIFIED, _S32,
        "Stopwatch counts up on panel; start-after-pause RESTARTS from zero rather than "
        "resuming (probes/probe_chronograph_clean.py, 2026-07-21). Caveat: with a paused "
        "countdown pending, chronograph commands acted on THAT state instead (sweep 2 "
        "2026-07-20) -- the native timer modes share device-side state. 2026-07-27 FOLLOW-UP "
        "(P7, probes/probe_p7_odds_and_ends.py phases 3-8): a targeted sequence -- arm a "
        "countdown from 5:00, pause it, then drive chronograph start/pause/resume/reset -- did "
        "NOT reproduce the 2026-07-20 hijack: chronograph.start() produced an INDEPENDENT "
        "stopwatch counting up from zero (seen at 14s), not a resumption of the paused "
        "countdown. chronograph.pause() froze the count; chronograph.resume() CONTINUED FROM "
        "THE FROZEN VALUE -- distinct from start(), which is MODE_START and always begins at "
        "zero, so this is not a contradiction of the restart-from-zero finding above, just a "
        "different command. chronograph.reset() zeroed it and it stayed at zero. THAT RUN'S "
        "CAVEAT IS NOW DISCHARGED 2026-07-28 (probes/probe_p7b_timer_state_unlabelled.py): P7 "
        "had flagged its own scoreboard phase labels as 'suspect #1 if the hijack fails to "
        "reproduce', since a label is itself a native-mode command and could have cleared the "
        "shared timer state before the interaction under test ever ran -- a concern vindicated "
        "the same day when P19 G3 showed labels silently switching modes mid-test and "
        "manufacturing two false entries on this very table. The label-free rerun sent THREE "
        "COMMANDS AND NOTHING ELSE (countdown.start(5,0), countdown.pause(), "
        "chronograph.start(); no scoreboard, no text, no reset) and got the SAME answer: the "
        "countdown froze at 04:48, and chronograph.start() showed 00:12 INCREMENTING across a "
        "12s window -- reset to zero and counting up freely, neither resuming 04:48 nor "
        "inheriting a paused state. So the 2026-07-20 hijack report is FALSIFIED on this "
        "firmware, not merely unreproduced: two runs agree and the instrumentation objection "
        "to the first is eliminated by construction. SCOPE, do not over-read it: only the "
        "ordering countdown-start/pause-then-chronograph-start was tested. The reverse order, "
        "countdown.restart() after a chronograph, and scoreboard interactions are all "
        "untested, so 'these two are independent for this sequence' is supported while 'no "
        "native timer modes share state' is NOT. Unrelated finding from the same phase: "
        "common.reset() briefly "
        "shows a RAINBOW pattern before the clock returns -- the device's flash/boot state "
        "(see common.reset).",
    ),
    Capability(
        "countdown", "set_mode", CapabilityStatus.VERIFIED, _S32,
        "30s countdown ran on panel, auto-returned to clock at zero; runs autonomously on "
        "device (probes/probe_capability_sweep1.py, 2026-07-20). MODE_DISABLE left resumable "
        "state rather than clearing (see chronograph caveat). OUT-OF-RANGE MINUTES ARE "
        "ACCEPTED-THEN-ABORTED 2026-07-25 (P13 phase C, probes/probe_boundary_sweep.py): a "
        "RAW [7,0,8,128,1,60,0] frame (60:00, bypassing the builder's minutes<=59 "
        "validation) was NOT nacked -- the device accepted it and then ABORTED the countdown "
        "that was already running, falling back to the clock. Neither clamped to 59:59 nor "
        "rejected. The builder's own minutes<=59 check is therefore load-bearing: without "
        "it an out-of-range value silently destroys a running countdown instead of failing "
        "loudly.",
    ),
    Capability(
        "clock", "show", CapabilityStatus.VERIFIED, _S32,
        "Clock ticks on RTC through disconnects; not flash-persisted (persistence probes "
        "2026-07-17; 3-run clock probe 2026-07-19; ROADMAP.md section 3 Native modes).",
    ),
    Capability(
        "clock", "style_select", CapabilityStatus.VERIFIED, _S32,
        "VERIFIED ON ALL EIGHT VALUES 2026-07-28 (P19 G3, probes/probe_p19_g3_clock_styles.py "
        "`sweep`): all eight styles sent in wire order 0..7, ~10 s each, colour held WHITE, date "
        "and 24h on, the sweep deliberately UNLABELLED so the panel never left clock mode. All "
        "eight acked ([05 00 06 01 01]) and the operator reported ALL EIGHT RENDERING AS DISTINCT "
        "FACES -- 'all the faces from the app'. The eight: 0 STYLE_RGB_SWIPE_OUTLINE, "
        "1 CHRISTMAS_TREE, 2 CHECKERS, 3 STYLE_COLOR, 4 HOURGLASS, 5 ALARM_CLOCK, 6 OUTLINES, "
        "7 RGB_CORNERS. THE OLD 'STYLE SELECTION APPEARS INERT' READING IS VOID, not softened: it "
        "came from probes/probe_p17b_eco_isolation.py phases 9-12, which exercised only styles 3 "
        "and 0 and SEPARATED ITS PHASES WITH SCOREBOARD LABELS. A label is itself a native-mode "
        "command, so the panel left and re-entered clock mode between phases and the style "
        "argument never got a clean test (PROBABLE cause; the precise mechanism -- style clobbered "
        "by the mode switch vs. re-entry defaulting it -- was not isolated and the corrected "
        "capability does not depend on it). G3 was built label-free for exactly that reason and "
        "immediately produced the opposite result. THE COLOUR ARGUMENT COLOURS THE DIGITS, on "
        "every style (P19 G3b, same probe, `sweep-red`: identical to `sweep` in every respect "
        "except the colour argument, RED instead of WHITE, so colour is the only variable between "
        "the two runs; all eight acked). Operator: ALL RED DIGITS, NO background fill anywhere, "
        "INCLUDING STYLE_COLOR (3). The earlier claim that STYLE_COLOR paints the BACKGROUND and "
        "renders the digits as black cutouts is FALSIFIED and DELETED. Independently corroborated "
        "by the vendor app the same night: it exposes exactly ONE colour setting, that setting "
        "changes the DIGIT colour, and it has no background-colour option at all -- the background "
        "claim was ours alone. METHODOLOGICAL NOTE, worth more than the fact: the background claim "
        "was 'corroborated' by lux -- P17b's clock phases read 63-65 against a full white field's "
        "65.8, i.e. near-full-panel emission, genuine physical evidence of a bright filled field "
        "-- but a scoreboard label sitting on the panel during those phases produces exactly that "
        "reading. THE LUX CORROBORATED THE LABEL, NOT THE STYLE. Two instruments agreeing is not "
        "validation when both share a confound. P17b's ENTIRE CLOCK-STYLE SECTION IS THEREFORE "
        "VOID AS A BLOCK, not item by item: the style-inertness reading, the background/"
        "digit-cutout reading, and the lux figures for those phases alike. Residual uncertainty, "
        "stated honestly: the WHITE sweep was never independently re-read for style 3 after the "
        "red result, so 'white behaves like red' is inferred from the simplest reading rather than "
        "directly observed -- reinstating a background-fill claim for any style needs a "
        "RED-equivalent reproduction, never a white one, since white-digits-on-black and "
        "white-field-with-black-digits are precisely what got confused the first time. STYLES 6 "
        "AND 7 ANIMATE (P19 G3c, red sweep; first record of ANY clock style animating): "
        "STYLE_OUTLINES (6) and STYLE_RGB_CORNERS (7) show blinking pixels / a heartbeat, and "
        "their colours render slightly OFF from what the app shows for the same styles. "
        "Unexplained and deliberately not chased -- possibly channel-order or palette handling on "
        "the animated sub-elements; no hypothesis committed. That some styles genuinely animate "
        "is also the shape of the old P17b phase-12 lux oscillation (32-48 on a repeating cycle "
        "against steady 63-65 elsewhere), though those figures are void with the rest of the "
        "block and cannot be used as evidence either way. MAGENTA DIGIT ORIGIN STILL UNRESOLVED, "
        "and the FAILED PREDICTION is recorded because it is informative: the two RGB_*-named "
        "styles (0 SWIPE_OUTLINE, 7 CORNERS) were predicted to IGNORE the colour argument and "
        "free-run through hues, which would have explained the early-P17 magenta digits with no "
        "colour-cycling-over-time hypothesis at all. FALSIFIED -- style 0 rendered RED digits like "
        "every other style, so it honours the colour argument and does not free-run, and style 7's "
        "animation is blinking corner pixels, not magenta digits. Now EXCLUDED as explanations: "
        "eco, clock style selection, the default colour argument (clock.show already defaults to "
        "white (255,255,255)), low-brightness channel dropout (see eco.lowlight_no_colour_shift), "
        "and RGB-style hue cycling. The remaining candidate is still that the face cycles colour "
        "on its own over time; the passive magenta watch stays queued in docs/PROBE_PLAN.md P19.",
    ),
    Capability(
        "scoreboard", "show", CapabilityStatus.VERIFIED, _S32,
        "12:34 rendered as two scores on panel (probes/probe_capability_sweep1.py, 2026-07-20). "
        "OUT-OF-RANGE SCORES ARE SILENTLY IGNORED 2026-07-25 (P13 phase D, probes/"
        "probe_boundary_sweep.py): a RAW [8,0,10,128,232,3,0,0] frame (score 1000, "
        "little-endian 0x03E8, bypassing the builder's 999 clamp) produced NO ACK AT ALL and "
        "the panel kept showing the previous 999. No nack, no 16-bit wrap to 000, no visible "
        "change -- the frame simply vanishes. The builder's 999 clamp is the only thing "
        "keeping an out-of-range score from being an invisible no-op.",
    ),
    Capability(
        "eco", "set_mode", CapabilityStatus.VERIFIED, _S32,
        "With the eco window covering now and eco_brightness=5, the panel visibly "
        "dimmed (probes/probe_capability_sweep3.py, 2026-07-21). CITATION CORRECTED "
        "2026-07-27: that 2026-07-21 run never set a prior brightness, so it could "
        "not actually establish 'disable restores brightness' -- restoring TO "
        "WHAT was never pinned down. The claim now rests on probes/"
        "probe_p17b_eco_isolation.py phases 4-8 and probes/probe_p17_brightness_eco.py "
        "Part B, both of which pin a KNOWN prior brightness (100) before eco ever "
        "runs. eco_brightness IS LIVE (falsifying the inert-parameter hypothesis "
        "this probe was built to test) and IS THE ORDINARY BRIGHTNESS SCALE, not a "
        "separate one: eco@5 measured 4.55 lux against a standalone brightness-5 "
        "reading of 4.69 lux, and eco@100 measured 65.23 lux against "
        "brightness-100's 65.84 lux. ECO OFF RESTORES THE HOST'S PINNED "
        "BRIGHTNESS (65.94 and 65.00 lux, both back at the ~65.84 reference, on "
        "the now-supported evidence). ECO IS A ONE-SHOT DIM, NOT A CLAMP: a host "
        "set_brightness(100) sent INTO an active eco window won outright -- the "
        "white field went fully bright and stayed there; eco sets the level once "
        "when its window opens and does not re-assert. THE ECO CONFIGURATION IS "
        "AUTONOMOUS DEVICE STATE: the dim survived a disconnect with no host "
        "attached, so a fresh client can inherit an eco window it cannot read "
        "back and that silently overrides brightness it never touched. ECO DOES "
        "NOT ALTER COLOUR: with eco armed and active but pinned to "
        "eco_brightness=100 (so brightness could not confound the reading), the "
        "clock face stayed white across eco-off/eco-on/eco-off. CORRECTION "
        "2026-07-27: the magenta digits seen in an earlier by-eye run were NOT "
        "traced to the dim brightness level after all -- see "
        "eco.lowlight_no_colour_shift, which EXCLUDES that explanation. The "
        "magenta digits' origin is UNRESOLVED; see clock.style_select.",
    ),
    Capability(
        "eco", "lowlight_no_colour_shift", CapabilityStatus.VERIFIED, _S32,
        "NO LOW-LIGHT COLOUR SHIFT 2026-07-27 (probes/probe_p17b_eco_isolation.py, colour + "
        "lowlight modes): a full-white field held at brightness 100/20/10/5 showed NO colour "
        "shift at any level. The RGB channels appear to share a single turn-on threshold "
        "rather than dropping out independently at low brightness. Consequence: the night-mode "
        "brightness recommendation (target 5-15, see common.set_brightness) stands with NO "
        "colour caveat. This is also the evidence that RETRACTS the earlier claim, previously "
        "recorded on eco.set_mode, that the magenta clock digits seen in an early P17 run were "
        "'traced to the dim brightness level itself' -- that explanation is now EXCLUDED, not "
        "confirmed. The magenta digits' origin remains genuinely unresolved; see "
        "clock.style_select's magenta-digit-origin note.",
    ),
    Capability(
        "color", "show", CapabilityStatus.VERIFIED, _S32,
        "Fullscreen color flash-persists across power-cycle -- survived 3 days, 2026-07 "
        "(persistence probes 2026-07-17; ROADMAP.md section 3 Display). CORRECTION 2026-07-27: "
        "P7 PHASE 9 WAS WRONGLY RECORDED AS VOID earlier the same day and is UN-VOIDED here. The "
        "void reasoning claimed our own reconnect repaints the clock via 'CCCD subscribe + "
        "set_time + a clock style command', citing the P1 HCI capture -- but that capture "
        "describes the VENDOR APP's connect sequence, observed only in the app's own traffic "
        "(docs/PROBE_PLAN.md P1). Our own connect path sends none of it: IDotMatrixClient."
        "connect() (client.py) only awaits BleTransport.connect() (transport/ble.py), which "
        "discovers, opens the GATT connection, subscribes to notifications, and fires the "
        "connected callback -- no set_time, no clock command, nothing that would repaint the "
        "screen. P7 phase 9's observation therefore stands as recorded: magenta fullscreen "
        "colour set, 12s disconnect, reconnect, and the panel showed the CLOCK, with nothing "
        "the SDK sent explaining the change. PHASE 9 RESOLVED 2026-07-27, and it is the EARLIEST "
        "INSTANCE OF LAZY DISPLAY-STATE PERSISTENCE on record here (see "
        "display.persistence_matrix). This caveat twice said otherwise -- first blaming a "
        "candidate 'reset shadow' (phase 9 in probes/"
        "probe_p7_odds_and_ends.py runs right after that probe's timer-state-machine cleanup, "
        "which calls common.reset() shortly before the magenta color.show()), then leaving open "
        "whether the loss was genuine device-side COLOUR VOLATILITY or a 'first-connection "
        "shadow' -- a model since RETRACTED. All of that is now closed. The reset is not the "
        "variable (`--no-reset` died identically). And the "
        "colour-volatility branch is DEAD: `--no-reset color` is "
        "phase 9's scenario reproduced under control -- fullscreen colour, written and then "
        "disconnected from ~8 s later with no prior reconnect -- and it died the same way, while "
        "the persistence matrix's colour row, armed with a prior reconnect behind it, HELD across "
        "the identical interruption. Phase 9 is therefore a short-dwell loss, chronologically the "
        "earliest and a third independent confirmation; fullscreen colour is DURABLE once it has "
        "dwelt or once the session has already reconnected. The phase-9 retest that used to be "
        "queued in docs/PROBE_PLAN.md is CANCELLED "
        "-- it would only re-run an answered discriminator. THE 3-DAY FIGURE AT THE TOP OF THIS "
        "ENTRY AND THE RECONNECT DEATHS ARE NOT IN CONFLICT, and this is now settled rather than "
        "merely 'consistent with' (2026-07-28, display.persistence_matrix's THREE DISTINCT DEVICE "
        "STATES note): the 3-day survival is the FLASH / BOOT state, which is what the panel "
        "powers on into; a reconnect does not restore that, it reasserts the ACTIVE display mode, "
        "which for a short-dwell write is whatever was last committed. A colour left alone for "
        "days is committed many times over; a colour written 8 s before a disconnect never was. "
        "BOTH RULES OF THUMB HOLD TOGETHER: colour is one of the most durable things this panel "
        "renders ONCE IT COMMITS, and one of the easiest to lose BEFORE it does. Fullscreen "
        "colour is also where condition (B) was first shown outside GIFs -- green written 10 s "
        "after a reconnect SURVIVED (P19 G7, probes/probe_p19_g7_isolated_dwell.py). "
        "CHANNEL EXTREMES MEASURED "
        "2026-07-25 (P13 phase B, probes/probe_boundary_sweep.py): every extreme is "
        "ACCEPTED and acked [05 00 02 02 01] -- there is no rejected RGB value -- but two "
        "ends of the range are not visually distinguishable from their neighbours. (1,1,1) "
        "renders as BLACK: it is below the LEDs' turn-on threshold and cannot be told apart "
        "from a dark panel, so callers must not use a near-black colour as a 'barely lit' "
        "signal. (254,254,254) is indistinguishable from full white. (255,0,255) is "
        "saturated magenta as expected. (0,0,0) is a plain black RASTER, NOT a powered-off "
        "panel -- the panel is still on and still in colour mode, so common.set_power(False) "
        "remains the only way to actually turn the display off.",
    ),
    Capability(
        "graffiti", "set_pixels", CapabilityStatus.VERIFIED, _S32,
        "Hardware-verified delta-render path; genuinely ack-silent, so the transport never "
        "awaits an ack for it (ROADMAP.md section 3 Display; FEATURE_MATRIX.md). App usage "
        "2026-07-25 (vendor-app HCI capture, tools/parse_btsnoop.py): the paint screen's ERASER "
        "is not a protocol feature at all -- it is a normal draw of color #000000 with move=0, "
        "which matches the falsified byte-4 ERASE hypothesis (see graffiti.move_type). The app "
        "only ever emitted single-pixel 10-byte commands, never a multi-pixel batch. DOES NOT "
        "COMPOSITE OVER A RUNNING NATIVE MODE 2026-07-27 (P12 sequence 2, see display."
        "invalidate_diy_mode): pixels sent while a native clock is showing, with no DIY entry, "
        "do NOT draw through onto the clock -- they force a MODE SWITCH instead. A caller must "
        "already be in the pixel/DIY framebuffer before graffiti deltas are safe; sent from a "
        "native-mode state it is not a safe overlay. *** 256 PIXELS IN ONE COMMAND KILLS THE "
        "DEVICE *** 2026-07-25 (P13 phase E, probes/probe_boundary_sweep.py) -- the "
        "highest-severity hazard on this table. A single RAW command carrying 256 coordinate "
        "pairs (size header (8,2) = 520 bytes, exactly ONE pixel over "
        "graffiti.MAX_PIXELS_PER_COMMAND=255) CRASHED THE PANEL'S BLE STACK: the GATT write "
        "failed mid-transfer ('Could not write value ... Unreachable'), the device STOPPED "
        "ADVERTISING entirely so reconnect raised BleakDeviceNotFoundError, the display went "
        "black, and a PHYSICAL POWER CYCLE was required to recover -- the probe's own "
        "clock-restore cleanup could not run. This is not a nack and not a recoverable error: "
        "there is nothing to catch and no software path back. The 255 cap is a hard safety "
        "limit, not a tuning constant. THE PUBLIC API IS SAFE: client.py's "
        "GraffitiFeature.set_pixels and display/ble_display.py's set_pixels both slice into "
        "MAX_PIXELS_PER_COMMAND-sized batches before building, so no public call can reach "
        "this. The hazard is reachable ONLY by hand-built raw commands that call "
        "build_set_pixels' wire layout directly -- which is precisely what probe scripts do, "
        "so any future probe author touching graffiti must respect the cap.",
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
        "cause (probe style/colors/method also differed) -- PROBE_PLAN P1-(c) runs the A/B. "
        "P1-(c) RESOLVED 2026-07-26/27 across three runs (probes/probe_effect_length_byte.py, "
        "probe_effect_length_byte2.py, probe_effect_speed_sweep.py). The FIVE-POINT SPEED "
        "SWEEP (run 3, speeds 5/25/50/75/100 at both the malformed 0x0d and correct 0x1c "
        "declared lengths, panel-labelled via the scoreboard) is the decisive run: pace rose "
        "MONOTONICALLY 5 -> 100 at BOTH declared lengths, and every one of the 10 phases "
        "rendered. Byte 5 IS a speed field, higher = faster: CONFIRMED, and this VERIFIED "
        "status stands. The MALFORMED-LENGTH-BYTE-HID-THE-SPEED-FIELD hypothesis is FALSIFIED "
        "-- the speed field responds correctly even behind the malformed 0x0d length, so the "
        "length byte was never the gate. Run 1's inverted-looking reading (speed 5 appearing "
        "faster than 100) is attributed to a design fault, not a device behavior: run 1 sent "
        "its four phases back to back with no clock reset between them, so phases 2-4 each "
        "landed on an already-running effect instead of a fresh mode entry, corrupting the "
        "pace comparison. RETRACTED: run 2's headline finding, 'all four 0x0d-declared frames "
        "drew no ack whatsoever', is WITHDRAWN as of run 3. It was an instrumentation bug, not "
        "a device behavior -- run 2 printed its ack report immediately after the send and "
        "cleared the list at the next phase boundary, before the device's ~4.3s reply for an "
        "effect command had arrived (see common.ack_timing, P14, which measured no silent "
        "command family at all). Every effect frame sent that night, at either declared "
        "length, in fact acked.",
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
        "music_sync", "set_mic_type", CapabilityStatus.VERIFIED, _S32,
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
        "animation'). CAVEAT ON THE SCOPE OF THIS VERIFICATION: only mic_type 1 with value 100 "
        "has ever been sent, so the entry certifies that the corrected SIX-BYTE FRAME reaches the "
        "device and changes what it renders -- what any OTHER mic_type value selects is entirely "
        "unobserved, and no value has been mapped to a named microphone/source setting.",
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
        "was a misread of silent failures). DISTRIBUTION CONFIRMS IT 2026-07-28 (P2b, probes/"
        "probe_p2b_terminal_status.py): seven uploads across two runs -- five cold seeds the "
        "device had never held, plus a cold-then-same-bytes pair -- ALL ended terminal 3. "
        "Terminal 3 means SAVED and carries NO information about novelty, so the single "
        "terminal-0 anecdote that prompted the original correction is now an outlier against "
        "seven 3s and reads as a genuine FAILED under the unified vocabulary (the driver now "
        "raises UploadError on anything but SAVED, so a repeat would surface loudly). WHAT "
        "DOES identify a duplicate is the ACK COUNT, an order of magnitude apart: a cold "
        "upload runs the full handshake (11-12 StatusAcks, ~8.3-8.7s) while a duplicate hits "
        "single-slot CRC recognition immediately (1 StatusAck, ~1.2s, no chunking). Callers "
        "must never read novelty off the terminal code; gif.activate_stored() is the exposed "
        "form of that check. Recognition is SINGLE-SLOT (device knows only the "
        "currently stored gif's CRC): chunk 1 of the stored gif SWITCHES PLAYBACK in ~1s with no "
        "artifacts (2026-07-25) -- a verified instant-takeover primitive, exposed as "
        "gif.activate_stored(). CHUNK-2 RACE proven visually 2026-07-25 "
        "(probes/probe_gif_color_reliability.py, tinted RED/GREEN/BLUE/YELLOW fixtures): ALL "
        "failures ever observed died at the chunk-2 position (+1.6-2.0s) -- RED and BLUE were "
        "silently doomed and left the previously stored color playing, while GREEN and YELLOW "
        "saved (terminal 3). Blind back-to-back sending hit ~50% silent failure on this panel "
        "(2 of 4). The SDK now PACES on the status handshake as of 2026-07-25 "
        "(client.py _send_gif_upload): send a chunk, await its StatusAck, restart the whole "
        "upload once on a doomed/timed-out pass -- the vendor app's own remedy for the race. "
        "INTERRUPTED-UPLOAD RECOVERY MAPPED 2026-07-27 (P10, probes/"
        "probe_p10_interrupted_upload.py): deliberately abandoning a replacement upload "
        "after its first BLE packet, after its first outer chunk, and mid-way through a "
        "later outer chunk NEVER CORRUPTED THE PREVIOUSLY STORED GIF -- checked each time "
        "via gif.activate_stored() against the old bytes, which kept returning SAVED. "
        "UploadError therefore means only 'the new content did not arrive', never 'and the "
        "old content is gone too', which is what makes _send_gif_upload's automatic "
        "whole-upload retry SAFE to run unattended. Two more results from the same run: a "
        "GIF already PLAYING FREEZES the instant a new upload starts arriving, rather than "
        "continuing to animate through the transfer; and gif.activate_stored() RESTARTS "
        "PLAYBACK AT FRAME 0 rather than resuming wherever the previous playback of that "
        "content had reached -- an instant-switch primitive (P2d), not a pause/resume one. "
        "RECOVERY RULE AFTER A SHORT-DWELL DISPLAY-STATE LOSS, 2026-07-28 (P19 G2, "
        "probes/probe_p11_persistence.py shadow-recover; full account in "
        "display.persistence_matrix): RE-ACTIVATE, DO NOT RE-TRANSFER. A GIF uploaded and then "
        "disconnected from ~8 s later, killed back to the clock by the reconnect, came back from "
        "gif.activate_stored() alone -- the stored bytes were still in flash, the device "
        "recognized their CRC (the call returned True and never requested a re-transfer), the "
        "animation rendered, and a control reconnect proved the restore durable. One small command "
        "instead of a whole chunked upload; only the current-mode pointer was ever lost. "
        "ACTIVATION IS NOT A COMMIT, 2026-07-28 (P19 G7, probes/probe_p19_g7_isolated_dwell.py, "
        "observed ONCE): activate_stored() put the stored noise GIF on screen and it stayed the "
        "ACTIVE display for 200 s -- longer than the 180 s dwell that committed a fullscreen "
        "colour in the same session's ladder -- yet the verification reconnect reverted to the "
        "EARLIER colour, so flash had never taken the GIF. Activating switches PLAYBACK without "
        "arming whatever the commit path is. Mechanism OPEN. PRACTICAL CONSEQUENCE: a re-activated "
        "GIF is NOT thereby protected -- it still needs dwell or a prior reconnect (see "
        "display.persistence_matrix's conditions (A) and (B)) before it will survive the NEXT "
        "interruption, and a probe that activates stored content as a 'decoy' has not persisted "
        "anything by doing so.",
    ),
    # --- common (device control) ---
    Capability(
        "common", "set_brightness", CapabilityStatus.VERIFIED, _S32,
        "5-100% works; out-of-range values nacked by the device via fa03 "
        "(ROADMAP.md section 3 Device). BOUNDARY CLOSED 2026-07-25 (P13, "
        "probes/probe_boundary_sweep.py): raw frames at 0/1/4/101/255 all NACK "
        "hard ([05 00 04 80 00]), no clamping -- the firmware's accepted range is "
        "exactly 5-100 and matches the SDK's own validation precisely. CROSS-MODE "
        "SEMANTICS 2026-07-27 (P17 Part A, probes/probe_p17_brightness_eco.py): "
        "brightness applies IMMEDIATELY and PERSISTS in every mode tested (DIY "
        "frame, GIF, effect, clock) -- never redraw-gated. Operator: 'the panel "
        "is 100%, the picture draws and then changes to 40%. If you then leave it "
        "there, the panel will stay there. Until you send another brightness "
        "command.' RESPONSE CURVE MEASURED 2026-07-27 (probes/"
        "probe_brightness_curve.py, an 11-rung ladder metered with a lux sensor "
        "at two distances, and probes/probe_p17b_eco_isolation.py phases 1-4): "
        "the curve is genuinely COMPRESSED, not a sensor artifact -- ratios "
        "measured at ~2in and ~4in from the panel agreed within 1-2% at every "
        "rung, which sensor saturation cannot survive. Brightness 50-100 are "
        "VISUALLY INDISTINGUISHABLE (40% already delivers within 6% of 100%'s "
        "output); the usable dimming range is roughly 5 to ~42, consistent with "
        "firmware computing something like min(255, percent*6). A distance-based "
        "correction on the record: the initial expectation that doubling the "
        "sensor distance would drop every reading ~4x (inverse-square, point "
        "source) was WRONG PHYSICS for this rig -- the panel is an extended "
        "source inside a small reflective chamber, and the measured drop between "
        "2in and 4in was ~0.74x, not ~4x. The within-run RATIO argument the curve "
        "conclusion rests on does not depend on that prediction being right, so "
        "the compressed-curve finding stands, but the 4x figure must not be "
        "reused as a calibration constant. BRIGHTNESS IS CONFIG-CLASS 2026-07-28 "
        "(P19 G1, probes/probe_p11_persistence.py --no-reset brightness): a "
        "brightness written seconds before a BLE reconnect survived both that "
        "reconnect -- which killed the white field it was set against -- and the "
        "software power cycle after it, and separately survived a PHYSICAL mains "
        "power cut. Brightness is flash-backed and is NOT subject to the LAZY "
        "DISPLAY-STATE PERSISTENCE that governs the current-mode pointer "
        "(display.persistence_matrix), so pinning it once at startup is safe and "
        "needs nothing to protect it.",
    ),
    Capability(
        "common", "set_power", CapabilityStatus.VERIFIED, _S32,
        "Power on/off exercised live (ROADMAP.md section 3 Device). SEMANTICS "
        "MAPPED 2026-07-27 (P7, probes/probe_p7_odds_and_ends.py phases 1-2): "
        "commands sent to a POWERED-OFF panel are still accepted and EXECUTE "
        "INVISIBLY -- the device keeps processing config and mode commands into "
        "an unseen framebuffer with the screen dark, rather than dropping them. "
        "turn_on() then REVEALS THE RESULTING FRAMEBUFFER: whatever was last "
        "commanded while off is what appears, not the mode that was showing "
        "before power-off and not a reset to clock. A caller that pushes frames "
        "into an off panel and gets clean acks back can be fooled into believing "
        "it is rendering; turn_on is a reveal, not a restore-to-prior-mode or a "
        "reset-to-clock operation.",
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
        "record. Its payload (a device/firmware descriptor?) is undecoded. UNCONDITIONALLY "
        "ACK-SILENT, SETTLED 2026-07-28 (P19 G4, probes/probe_p19_g4_settime_acks.py `full`): "
        "SEVEN RTC jumps drew ZERO acks each -- three with a schedule theme armed, three with both "
        "theme slots disarmed (StatusAck 3 each) and the schedule master switch OFF, plus a "
        "seventh pre-arm jump -- at a 2.5 s settle, with the ack list never read early and never "
        "cleared. THE ARMED-SCHEDULE HYPOTHESIS IS FALSIFIED: the theme is not the variable, "
        "set_time simply never acks on this panel. P5's contrary reading (TWO acks per call with "
        "the subsystem idle) is the lone outlier against those seven and is SUPERSEDED -- most "
        "probably an ack-attribution artifact, neighbouring commands' acks landing in the "
        "measurement window, the same failure class corrected elsewhere that session; PROBABLE, "
        "not established. Consistent with the vendor-app capture above: what the app's set_time "
        "drew was a 9-byte frame, not a 5-byte ack, and protocol/response.py returns None for it. "
        "CONSEQUENCE, IMPLEMENTED: client.set_time is fire-and-forget (verify=False) as of this "
        "finding. It is NOT a hang hazard either way -- transport.await_device_ack returns None on "
        "a bounded timeout by design -- but awaiting it burned the full _DEFAULT_ACK_TIMEOUT "
        "(2.0 s, transport/ble.py) on EVERY call, and set_time is typically a caller's first write "
        "of every connection, so every startup, reconnect and self-heal silently paid it. See "
        "common.ack_timing for the scoping of P14's 'no family was ever silent'.",
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
        "Used live 2026-07-18 to clear a stuck state (ROADMAP.md section 3 Device). BOOT/FLASH "
        "STATE IDENTIFIED 2026-07-27 (P7, probes/probe_p7_odds_and_ends.py, the chronograph/"
        "countdown branch): after a common.reset(), the panel briefly shows a RAINBOW pattern "
        "before the clock returns -- the device's flash/boot state, useful as a visual landmark "
        "for 'the device is mid-reset' in future probes. RESET IS EXONERATED, correction "
        "2026-07-27 (see display.persistence_matrix): this entry previously recorded a GIF "
        "uploaded immediately after reset() failing to persist as an open question about reset's "
        "aftermath. It is not reset's aftermath -- `--no-reset gif` died identically, twice, so "
        "the operative factor is LAZY DISPLAY-STATE PERSISTENCE (display.persistence_matrix) and "
        "reset is not involved at all. reset() is a safe launchpad for an immediate upload; "
        "disconnecting a few seconds after one is what is not safe.",
    ),
    Capability(
        "common", "ack_timing", CapabilityStatus.VERIFIED, _S32,
        "CALIBRATED 2026-07-27 (P14, probes/probe_p14_ack_timing.py: 7 command families, 5 "
        "repeats each, verification off so the measured t=0 is GATT write completion, not the "
        "SDK's own internal ack-await). NO COMMAND FAMILY TESTED WAS SILENT IN P14'S CONDITIONS "
        "-- brightness (valid and out-of-range), scoreboard, effect, clock, a full DIY frame, and "
        "chunked GIF upload all acked on every repeat. SCOPE, and a CONFIRMED EXCEPTION: P14 did "
        "not test common.set_time at all, and set_time is a genuinely silent family. P19 G4 "
        "(probes/probe_p19_g4_settime_acks.py, 2026-07-28) counted ZERO acks on seven RTC jumps "
        "spanning armed and disarmed schedule themes and the master switch both ways, at a 2.5 s "
        "settle -- so 'no command family tested was silent' holds for P14'S SEVEN FAMILIES ONLY "
        "and must not be read as a device-wide rule. ARMED SCHEDULE STATE IS NOT the variable it "
        "was suspected to be: P14 ran with an IDLE schedule subsystem, but G4's control half was "
        "genuinely unarmed and set_time was silent there too. P5's (probes/probe_p5_schedule.py, "
        "2026-07-27) contrary observation of TWO acks per set_time call with the subsystem idle is "
        "SUPERSEDED by those seven -- probably an ack-attribution artifact rather than a device "
        "behaviour (see common.set_time). First-ack latency clustered by family: FLAT config/"
        "native-mode commands (brightness, scoreboard, clock) replied in roughly 0.13-0.30s; "
        "FULL-FRAME commands (the DIY frame, and the effect command) replied in roughly "
        "0.6-0.9s. This directly RETRACTS the 2026-07-26 'all four 0x0d effect frames drew no "
        "ack whatsoever' finding (probes/probe_effect_length_byte2.py): that was an "
        "instrumentation bug (see effect.speed's retraction note below), not a device or "
        "declared-length-byte behavior, and the corrected latency figures here are the ones "
        "to design timeouts against -- transport.await_device_ack's 2.0s default has margin "
        "over every measured family.",
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
        "experimental", "timer_close", CapabilityStatus.VERIFIED, _S32,
        "Sent to hardware, but the ack is a state echo (statuses 0/1/3 observed from different "
        "states), so the disarm effect was long unconfirmed (probes/probe_timer_close.py; "
        "ROADMAP.md section 3 Alarms). MECHANISM ESTABLISHED 2026-07-27 (P6, probes/probe_p6_"
        "alarms.py, isolated `q3` mode, reproduced twice from a fresh reset): timer_close "
        "clears the slot's CONTENT but leaves its SCHEDULE and BUZZER armed -- it is a PARTIAL "
        "disarm, not a full one. Slot 0 was armed for 12:02 (red content, buzzer=True) and "
        "closed; at 12:02 the buzzer still SOUNDED and the panel showed BLUE (slot 1's "
        "content), not red and not silence. The identical arming sequence WITHOUT the close "
        "produced RED at 12:02, so the close is the only variable and the effect is real. "
        "RETRACTS the earlier framing above: 'timer_close does not disarm' was HALF RIGHT -- "
        "it disarms the content, not the alarm. A caller relying on timer_close to fully "
        "silence a slot will still get the buzzer. STATE-ECHO VOCABULARY CORRECTED, same "
        "session: arm returns status 3 (SAVED); closing a slot that still holds content also "
        "returns status 3 ('had content, now cleared'); closing an empty or already-fired slot "
        "returns status 0 -- NOT the status 1 this claim rested on in the 2026-07-12 session "
        "and in protocol/timer.py's build_timer_data_packets docstring. That status-1 reading "
        "has not been reproduced this session; treat 0, not 1, as the current best evidence for "
        "'empty/consumed' pending a direct re-check, since a single state-echo digit is exactly "
        "the kind of thing easy to misread under the ack-timing bugs this lab has hit before.",
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
        "against the device RTC weekday. Fire signature: buzzer first, content ~1-2s later. "
        "MULTI-SLOT BEHAVIOR MAPPED 2026-07-27 (P6, probes/probe_p6_alarms.py): two "
        "independently armed slots BOTH fire, in armed-minute order -- slot 0 (red, "
        "buzzer=True) fired red WITH the beep, slot 1 (blue, buzzer=False) fired blue "
        "SILENTLY, one minute later; per-slot buzzer confirmed. ALARMS ARE FLASH-PERSISTENT: "
        "arm -> physical power-cycle -> check reconnected with both slots firing again "
        "unprompted, payloads intact (red+beep at 12:34, blue at 12:35) -- GlanceOS can rely "
        "on device-side alarm storage rather than re-arming on every reconnect. COLLISION "
        "RULE: when two slots are armed for the SAME minute, the HIGHER SLOT INDEX wins the "
        "DISPLAY regardless of arming order or payload colour (four combinations of index x "
        "order x colour tested, same winner every time). BOTH buzzers still sound in a "
        "collision -- the loser's content simply never reaches the panel at all, it is not "
        "overwritten: the loser's close-ack read status 3 ('still had content, never "
        "consumed') while the winner's read status 0 ('fired and consumed'). Design rule for "
        "GlanceOS M7 Stage 4: put the alarm meant to be SEEN in the higher slot index. See "
        "experimental.timer_close for the disarm-semantics and state-echo-vocabulary "
        "correction this same session produced.",
    ),
    Capability(
        "experimental", "schedule_set_theme", CapabilityStatus.VERIFIED, _S32,
        "GIF theme upload SAVED and fired inside its window 2026-07-12 -- end boundary looked "
        "minute-exclusive (probes/probe_schedule_gif.py; ROADMAP.md section 3 Alarms). Image "
        "content is PNG, not raw RGB (APK_SECOND_PASS.md Q2). DAY-BIT MAP CONFIRMED and PNG "
        "RENDERING CONFIRMED 2026-07-27 (P5, probes/probe_p5_schedule.py, RTC-spoofed): a "
        "theme armed for a single weekday's bit FIRED when the device RTC was spoofed to that "
        "weekday and stayed silent (clock face, no content) when spoofed to a different, "
        "non-adjacent weekday with nothing re-armed -- confirming Schedule's patch_week() "
        "source-traced encoding on hardware for the first time (Timer's own week-bit map does "
        "not call patch() and so never covered this). A PNG (CONTENT_IMAGE) theme rendered as "
        "a static image inside its window, resolving the last untested Schedule content path. "
        "WINDOW BOUNDARY RESOLVED 2026-07-27 (P5b, probes/probe_p5b_window_boundary.py, "
        "control+test pair): Schedule is evaluated on MINUTE TICKS, not continuously. Jumping "
        "the RTC directly to 12:11:30 -- inside the armed 12:10-12:12 window -- fired NOTHING; "
        "content only appeared once the device's own clock naturally rolled over to the next "
        "minute, 12:12:00. Landing mid-window via set_time therefore fires nothing on its own. "
        "THE END MINUTE IS INCLUSIVE: content was up at that 12:12:00 tick, and a second run "
        "that jumped 30s into the end minute (12:12:30) and then watched across the 12:13:00 "
        "tick found nothing there -- the window covers 12:10, 12:11 and 12:12, and is closed "
        "by 12:13. This OVERTURNS the 2026-07-12 'looks minute-exclusive' reading recorded "
        "above: that observation was an artifact of the same minute-tick evaluation, not yet "
        "understood at the time, not a genuinely exclusive boundary. Design consequence: a "
        "[T, T+2min] Schedule window is a full 3 calendar minutes long, and content changes "
        "are only ever visible at a minute rollover, never mid-minute.",
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
