# Reverse-engineering notes

This directory is the migrated decompile-analysis record behind pyidotmatrix's
protocol knowledge. All five documents were produced against the same source:
the decompiled `com.tech.idotmatrix` Android APK, version string
`iDotMatrix_2026_06_29_19_07-v2.1.2_googleRelease` (v2.1.2, googleRelease,
built 2026-06-29). They were written before this SDK was extracted into its
own repository, in a research lab that also housed BLE probe scripts and an
early driver prototype — see the provenance header at the top of each file
before trusting any path it mentions.

## What each document is

**[APK_RESEARCH_HANDOFF.md](APK_RESEARCH_HANDOFF.md)** — the orientation
document. Read this first: it explains the reading order for the other three
findings docs, states the ground rules for what counts as "confirmed" versus
"hypothesis," and lays out a priority order for turning findings into ported
code. Short, and mostly still accurate as a methodology reference even though
its file paths point at the old lab layout.

**[FEATURE_MATRIX.md](FEATURE_MATRIX.md)** — a feature-by-feature table
comparing every protocol capability found in the decompiled APK against what
the driver implemented at the time of writing. Each row cites the APK source
class/method and a status (byte-confirmed, gap, not investigated, out of
scope, or blocked). This is the widest-angle view of the protocol surface;
start here if you want to know "does the vendor app do X, and do we?"

**[APK_PROTOCOL_FINDINGS.md](APK_PROTOCOL_FINDINGS.md)** — byte-level detail
for the driver gaps identified in the feature matrix: `verify_password`,
`set_time_indicator`, `delete_device_data`, the screen-timeout family, the
`DiyImageFun` DIY-mode constants, and the graffiti "mirror" byte hypothesis.
Each finding is graded confirmed / hypothesis / blocked and includes the
decompiled Java alongside the equivalent Python builder.

**[ALARM_BUZZER_APK_FINDINGS.md](ALARM_BUZZER_APK_FINDINGS.md)** — a focused
map of the Timer (alarm) and Schedule (weekly theme) subsystems: packet
headers byte-by-byte, content-type encoding, duration tables, week-bitmask
packing, ack vocabularies, and a suggested hardware-verification order. This
is the document that unblocked alarm/schedule support — treat it as a map for
verification work, not a finished, hardware-checked spec.

**[APK_SECOND_PASS.md](APK_SECOND_PASS.md)** — a targeted follow-up pass
written after hardware testing contradicted or exceeded claims in the two
findings docs above. It resolves five specific questions (wire endianness,
Timer/Schedule image content format, week-bitmask day mapping, ack
correlation in the vendor app, and a few opportunistic reads on effects and
pixel dimming) with source citations, and explicitly calls out which earlier
claims it corrects rather than silently editing them.

## Relationship to `probes/`

These documents are decompile analysis: they describe what the vendor app's
*source code* does, graded by confidence (confirmed-from-source / hypothesis
/ blocked, or the earlier documents' ✅/⚠️/🔍/❌/🚫 shorthand). They are not,
by themselves, proof of hardware behavior — a byte layout read correctly out
of a decompiled APK can still be wrong about what the firmware actually does
when it receives those bytes.

The `probes/` directory one level up is the executable evidence: scripts that
send these hypothesized commands to a real panel and record what happens.
Where a probe exists and has been run, its result is the authoritative
answer; where it hasn't, a finding here remains a hypothesis regardless of
how confident the source reading was. Cross-reference specific probes named
in the roadmap's capability inventory when you want to know whether a claim
in these documents has since been hardware-verified.

## Evidence conventions

The rest of this SDK's documentation (starting with
[ROADMAP.md](../ROADMAP.md)) tags every capability with one of:

- ✅ **Hardware-verified** — observed on a real panel, with the probe/date cited.
- ⚠ **Experimental** — decoded and source-confirmed from the vendor APK, but not
  verified on hardware (or verified *broken*, where flagged).
- ❓ **Reverse engineering in progress** — existence known; wire format partial
  or unknown.

The documents in this directory predate that exact convention and use their
own confidence labels (per-document, described above), but they map onto it
directly: CONFIRMED-FROM-SOURCE / ✅-in-matrix findings are the ⚠ tier once
they're source-confirmed-but-unverified, and graduate to ✅ only once a probe
under `probes/` confirms them on real hardware. See ROADMAP.md §15 for the
full ⚠→✅ graduation process.
