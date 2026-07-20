"""Tests that the capability table is complete, evidence-backed, and read-only."""

import re

import pytest

from pyidotmatrix import CAPABILITIES, Capability, CapabilityStatus, capability
from pyidotmatrix.screen import ScreenSize

# The feature namespaces IDotMatrixClient exposes (mirrors
# test_client.test_all_feature_namespaces_present).
CLIENT_NAMESPACES = (
    "chronograph", "countdown", "clock", "scoreboard", "eco",
    "color", "graffiti", "effect", "music_sync", "text", "gif", "common", "display",
    "experimental",
)


def test_every_client_namespace_is_covered():
    covered = {entry.feature for entry in CAPABILITIES.values()}
    for namespace in CLIENT_NAMESPACES:
        assert namespace in covered, f"no capability entry for namespace: {namespace}"


def test_no_entry_for_a_nonexistent_namespace():
    # The table only makes claims about namespaces the client actually has.
    for entry in CAPABILITIES.values():
        assert entry.feature in CLIENT_NAMESPACES, f"unknown feature: {entry.feature}"


def test_every_entry_has_real_evidence():
    for entry in CAPABILITIES.values():
        assert isinstance(entry.evidence, str)
        assert len(entry.evidence) >= 20, f"{entry.name}: evidence too thin to be real"
        # Every evidence string names at least one concrete source: a probe
        # script, an RE doc, the ROADMAP inventory, or a dated session.
        assert re.search(
            r"probes/|APK_|ALARM_BUZZER|FEATURE_MATRIX|ROADMAP\.md|20\d\d-\d\d(-\d\d)?",
            entry.evidence,
        ), f"{entry.name}: evidence cites no probe/doc/date: {entry.evidence!r}"


def test_statuses_are_enum_members_and_sizes_are_screen_sizes():
    for entry in CAPABILITIES.values():
        assert isinstance(entry.status, CapabilityStatus)
        assert entry.screen_size is None or isinstance(entry.screen_size, ScreenSize)


def test_keys_match_entry_names():
    for key, entry in CAPABILITIES.items():
        assert key == entry.name == f"{entry.feature}.{entry.command}"


def test_verified_entries_carry_a_screen_size():
    # A VERIFIED or KNOWN_BROKEN claim is a hardware observation, which only
    # ever happened on a specific panel; it must say which one.
    for entry in CAPABILITIES.values():
        if entry.status in (CapabilityStatus.VERIFIED, CapabilityStatus.KNOWN_BROKEN):
            assert entry.screen_size is not None, f"{entry.name}: hardware claim without a panel size"


def test_lookup_and_unknown_name():
    entry = capability("text.show")
    assert entry.status is CapabilityStatus.VERIFIED
    assert entry.screen_size is ScreenSize.SIZE_32x32
    with pytest.raises(KeyError):
        capability("text.does_not_exist")


def test_spot_checks_match_the_evidence_record():
    assert capability("common.set_screen_timeout").status is CapabilityStatus.KNOWN_BROKEN
    assert capability("common.verify_password").status is CapabilityStatus.SOURCE_DERIVED
    # 2026-07-21 sweep: chunked framing acked but inert on hardware.
    assert capability("effect.show_chunked").status is CapabilityStatus.KNOWN_BROKEN
    # 2026-07-21: byte 3 is not a mirror field -- only 1 draws; the transform
    # field is byte 4 (DiyImageMoveType), both hardware-mapped.
    assert capability("graffiti.byte3_required_one").status is CapabilityStatus.VERIFIED
    assert capability("graffiti.move_type").status is CapabilityStatus.VERIFIED
    assert capability("experimental.timer_set").status is CapabilityStatus.VERIFIED
    # 2026-07-20/21 sweep: native modes and eco moved to VERIFIED.
    assert capability("eco.set_mode").status is CapabilityStatus.VERIFIED
    assert capability("common.freeze_screen").status is CapabilityStatus.KNOWN_BROKEN


def test_table_is_read_only():
    with pytest.raises(TypeError):
        CAPABILITIES["common.reset"] = None  # type: ignore[index]
    entry = capability("common.reset")
    with pytest.raises(AttributeError):
        entry.status = CapabilityStatus.UNKNOWN  # type: ignore[misc]


def test_capability_is_hashable_dataclass():
    assert isinstance(capability("clock.show"), Capability)
    assert len({entry for entry in CAPABILITIES.values()}) == len(CAPABILITIES)
