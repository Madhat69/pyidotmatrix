"""Prints the SDK's machine-readable maturity story: every entry in
CAPABILITIES, and how to check a feature's status before calling it.

What this shows:
    - CAPABILITIES / capability() -- the evidence-backed table behind every
      status tag in docs/features.md and docs/hardware-compatibility.md
    - CapabilityStatus -- VERIFIED / SOURCE_DERIVED / UNKNOWN / KNOWN_BROKEN
    - guarding a call on KNOWN_BROKEN before sending it, using
      common.freeze_screen (acked by the device but with no observable
      effect on the reference panel -- see capabilities.py) as the example

Hardware needed: none. This is pure local data -- no connection is opened.

    python examples/08_capability_table.py
"""

from pyidotmatrix import CAPABILITIES, CapabilityStatus, capability

# One column width per field, for a readable fixed-width table.
_FEATURE_COMMAND_WIDTH = 28
_STATUS_WIDTH = 15

_STATUS_MARKERS = {
    CapabilityStatus.VERIFIED: "✅",        # hardware-confirmed working
    CapabilityStatus.SOURCE_DERIVED: "⚠",  # bytes confirmed, not hardware-exercised
    CapabilityStatus.UNKNOWN: "❓",         # wire bytes exist, meaning unknown
    CapabilityStatus.KNOWN_BROKEN: "✖",    # sent to hardware, observed NOT working
}


def print_table() -> None:
    """The full table, one row per "feature.command" entry, sorted for a
    stable read. Evidence strings are long by design (they cite the probe
    or doc section) -- truncated here only for terminal width."""
    header = f"{'feature.command':<{_FEATURE_COMMAND_WIDTH}} {'status':<{_STATUS_WIDTH}} evidence"
    print(header)
    print("-" * len(header))
    for name in sorted(CAPABILITIES):
        entry = CAPABILITIES[name]
        marker = _STATUS_MARKERS[entry.status]
        evidence_preview = entry.evidence[:80] + ("..." if len(entry.evidence) > 80 else "")
        print(f"{marker} {name:<{_FEATURE_COMMAND_WIDTH - 2}} {entry.status.value:<{_STATUS_WIDTH}} {evidence_preview}")


def guard_before_calling(name: str) -> bool:
    """The pattern this module exists to demonstrate: look a capability up
    before sending its command, and treat KNOWN_BROKEN as "don't bother" --
    the device will ack it, but it won't do anything.

    capability() raises KeyError for a name that isn't in the table at all;
    that's "not yet inventoried", distinct from a known-bad status.
    """
    entry = capability(name)
    if entry.status is CapabilityStatus.KNOWN_BROKEN:
        print(f"skipping {name}: KNOWN_BROKEN -- {entry.evidence[:100]}...")
        return False
    print(f"{name} is {entry.status.value} -- safe to try (an ack still isn't proof of effect).")
    return True


def main() -> None:
    print_table()

    print("\n--- guard example ---")
    # common.freeze_screen is KNOWN_BROKEN on the reference panel (acked, no
    # observable effect) -- exactly the case this table exists to flag before
    # a caller wastes a round-trip on it.
    if guard_before_calling("common.freeze_screen"):
        pass  # would call client.common.freeze_screen() here
    guard_before_calling("clock.show")  # VERIFIED -- the contrast case


if __name__ == "__main__":
    main()
