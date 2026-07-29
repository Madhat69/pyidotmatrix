"""Tests that probe records cannot drift silently.

A probe's status lives in three places -- the `## P<n>` heading in
docs/PROBE_PLAN.md, that section's prose, and the RESULT block in the probe file
itself -- and nothing used to force them to agree. They drifted repeatedly: P3
and P8 were closed in body text with no heading marker, P1-(c) still advertised
itself as "next session" a day after it ran, and P13 ran a full boundary sweep
whose findings (including a hard device kill) sat in the probe file alone for
three days because recording was deferred to avoid an edit collision and then
forgotten.

These tests do not check that a status is CORRECT -- only a human at the panel
can say that. They check that a status was RECORDED AT ALL, which is the failure
mode that actually happened.
"""

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROBES_DIR = _REPO_ROOT / "probes"
_PROBE_PLAN = _REPO_ROOT / "docs" / "PROBE_PLAN.md"

# Files under probes/ that are shared helpers rather than probes in their own
# right, so they have no result to record. Keep this list short and justified:
# anything that talks to the panel and answers a question is a probe.
_NOT_PROBES = frozenset(
    {
        "_reset_once.py",  # one-shot reset helper, invoked by hand between probes
    }
)

# Probes written before the RESULT convention existed. Their findings ARE
# recorded -- in capabilities.py and docs/PROBE_PLAN.md -- but not in the probe
# file, so a reader opening one of these cannot tell what it found or whether it
# ever ran. This list is a visible backlog, not an exemption: shrink it whenever
# one of these is touched, and never add to it. New probes must record a RESULT.
_PREDATES_RESULT_CONVENTION = frozenset(
    {
        "probe_capability_sweep1.py",
        "probe_capability_sweep2.py",
        "probe_capability_sweep3.py",
        "probe_chronograph_clean.py",
        "probe_content_image_and_recolor.py",
        "probe_diy_modes.py",
        "probe_effect_set_speed.py",
        "probe_effect_speed.py",
        "probe_effect_speed2.py",
        "probe_graffiti_byte3_final.py",
        "probe_graffiti_byte3_state.py",
        "probe_graffiti_byte3_state2.py",
        "probe_graffiti_mirror.py",
        "probe_graffiti_movement.py",
        "probe_graffiti_movetype.py",
        "probe_graffiti_transform.py",
        "probe_graffiti_transform2.py",
        "probe_schedule_gif.py",
        "probe_schedule_master_switch.py",
        "probe_screen_timeout.py",
        "probe_timer_close.py",
        "probe_timer_image.py",
        "probe_timer_weekbit.py",
        "probe_verify_password.py",  # never run, and gated behind an interlock
    }
)

# A probe records its outcome with a RESULT block in the module docstring.
# "pending" is allowed -- an authored-but-unrun probe is a legitimate state, and
# saying so explicitly is the whole point.
_RESULT = re.compile(r"^RESULT\b", re.MULTILINE)

# Heading status markers PROBE_PLAN.md uses. OPEN covers probes that are
# authored or merely planned but have no panel result yet.
_STATUS_MARKERS = ("✅", "⚠", "⬜", "⭐", "(open)", "OPEN")

_PLAN_HEADING = re.compile(r"^#{2,3} (P\d+(?:-\([a-z]\))?)\b.*$", re.MULTILINE)


def _probe_files() -> list[Path]:
    skip = _NOT_PROBES | _PREDATES_RESULT_CONVENTION
    return sorted(p for p in _PROBES_DIR.glob("*.py") if p.name not in skip)


def test_grandfather_list_has_no_stale_entries():
    """The backlog must shrink honestly, not accumulate names of deleted files."""
    missing = sorted(name for name in _PREDATES_RESULT_CONVENTION if not (_PROBES_DIR / name).exists())
    assert not missing, "_PREDATES_RESULT_CONVENTION names files that no longer exist; remove them:\n  " + "\n  ".join(
        missing
    )


def test_grandfathered_probes_still_lack_a_result():
    """When a grandfathered probe gains a RESULT, take it off the list.

    Without this the backlog would never shrink -- entries would sit there
    exempting probes that had long since been documented.
    """
    documented = sorted(
        name for name in _PREDATES_RESULT_CONVENTION if _RESULT.search((_PROBES_DIR / name).read_text(encoding="utf-8"))
    )
    assert not documented, (
        "these probes now have a RESULT block -- remove them from "
        "_PREDATES_RESULT_CONVENTION:\n  " + "\n  ".join(documented)
    )


def test_probes_directory_is_found():
    """Guards against the glob silently matching nothing if layout changes."""
    assert _probe_files(), f"no probe files found under {_PROBES_DIR}"


@pytest.mark.parametrize("probe", _probe_files(), ids=lambda p: p.name)
def test_every_probe_records_a_result(probe: Path):
    """Every probe states what happened when it ran -- or that it has not run.

    A probe whose findings live only in the operator's memory (or only in a
    chat transcript) is a probe whose findings will be lost.
    """
    text = probe.read_text(encoding="utf-8")
    assert _RESULT.search(text), (
        f"{probe.name} has no RESULT block. Add one to the module docstring, "
        f"even if it is just 'RESULT (YYYY-MM-DD): pending -- not yet run.'"
    )


def test_probe_plan_headings_all_carry_a_status():
    """Every P-section in the plan says where it stands.

    Body prose does not count: a reader scanning headings must not be told a
    probe is pending when it closed days ago.
    """
    plan = _PROBE_PLAN.read_text(encoding="utf-8")
    unmarked = [
        match.group(0)
        for match in _PLAN_HEADING.finditer(plan)
        if not any(marker in match.group(0) for marker in _STATUS_MARKERS)
    ]
    assert not unmarked, (
        f"PROBE_PLAN.md headings without a status marker ({', '.join(_STATUS_MARKERS)}):\n  " + "\n  ".join(unmarked)
    )


def test_probe_plan_is_not_empty():
    """Guards against the heading regex matching nothing after a reformat."""
    plan = _PROBE_PLAN.read_text(encoding="utf-8")
    assert len(_PLAN_HEADING.findall(plan)) >= 15, (
        "found fewer P-sections than expected in PROBE_PLAN.md -- has the "
        "heading format changed? This test's regex needs updating with it."
    )
