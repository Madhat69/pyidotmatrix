# Contributing to pyidotmatrix

Thanks for considering it. This project has two equally important goals: the
best Python SDK for iDotMatrix BLE displays, and the reference documentation
of how the device protocol actually behaves. Contributions to either count.

## Reverse engineering is a first-class contribution

You do not need to write a line of SDK code to make a meaningful
contribution. All of the following are as valuable as production code, and
are reviewed and credited the same way:

- **Hardware probes and their logs** — including negative results. "I ran
  this against a 64×64 panel and it did nothing" is useful data.
- **BLE packet captures** of the vendor app talking to a real device.
- **Firmware/model behaviour comparisons** — 16×16, 32×32, 64×64, or any
  other panel size/revision we don't already have coverage for.
- **APK analysis** of new vendor app releases (protocol changes, new
  commands, byte-layout corrections).
- **Protocol documentation and corrections** — including fixing something an
  earlier finding got wrong. See `docs/reverse-engineering/APK_SECOND_PASS.md`
  for what a good correction pass looks like: it named exactly which earlier
  claims were wrong and why, without hiding the mistake.
- **Behaviour verification of ⚠-tagged features** on real panels — this is
  how a capability moves from "we think this is the byte layout" to "we know
  this works."

If you have a panel we don't, you can move features from ⚠ to ✅ in the
capability table without touching the SDK's Python at all.

## Running the test suite

```
pip install -e .[test]
pytest
```

The suite is byte-exact protocol tests plus transport/simulator tests. None
of it talks to real hardware — it runs in CI on every push and PR (see
`.github/workflows/ci.yml`).

## Running probes — real hardware only, human-run, never CI

Scripts under `probes/` talk to a real panel over BLE. They exist to turn a
hypothesis from the reverse-engineering docs into a hardware-verified fact
(or disprove it). Rules:

- **Run them yourself, by hand, against a panel you own.** They are not part
  of the test suite and must never run in CI — there is no hardware there,
  and some of them are destructive.
- **Read the script before running it.** Several probes send commands that
  are irreversible or disruptive: `probe_timer_close.py`, anything touching
  `delete_device_data`, and similar destructive operations sit behind
  explicit `confirm=True` flags (or an equivalent guard) precisely so you
  don't fire them by accident. Do not remove or bypass that guard to "just
  try it."
- **Record what happened**, including failures. A probe log that says "this
  did not work" is a real contribution — see the reverse-engineering section
  above.
- If a probe's result contradicts something in `docs/reverse-engineering/` or
  `docs/ROADMAP.md`, that's a bug report against the docs, not against your
  hardware. Open an issue or PR with the correction.

## The ⚠ → ✅ graduation process

A capability moves out of experimental status through four steps (full
policy: `docs/ROADMAP.md` §15):

1. **Wire format source-confirmed** — the byte layout is read from the
   vendor APK or an equivalent authoritative source, not guessed.
2. **Hardware-verified** on at least one real model, with the probe run and
   its evidence (script + date + result) recorded.
3. **Byte-exact regression test** added, so the finding can't silently regress.
4. **Documented** in the capability table with its status tag.

Once all four are true, the feature graduates out of `.experimental` (or its
⚠ tag flips to ✅) in the next minor release. Everything under
`.experimental`, and anything still tagged ⚠, is explicitly exempt from
SemVer guarantees — it can change or disappear without a major-version bump.

## Code contributions

If you're changing SDK code rather than researching the protocol, the
layered architecture is the contract to respect:

- **Protocol builders** (`pyidotmatrix/protocol/`) are pure — no I/O, no BLE,
  just bytes in, bytes out. They should be trivially unit-testable without a
  device or even a mock transport.
- **Transport** is feature-agnostic — it moves bytes, manages the connection
  lifecycle, and correlates acks. It should never know what a "clock" or a
  "gif" is.
- Everything above transport (display backends, the client façade) composes
  the two without leaking protocol details upward or transport concerns
  downward.

New protocol builders should come with byte-exact tests, ideally citing the
probe or APK finding that justifies the byte layout, the same way the
existing tests and `docs/reverse-engineering/` findings do.

## License and attribution

This project is licensed **GPL-3.0-or-later** (see `LICENSE`). By
contributing, you agree your contribution is licensed under the same terms.

Several source files carry per-module attribution comments crediting the
reverse-engineering lineage this SDK builds on (see `NOTICE`). Preserve those
comments when you touch a file they're in — they're not boilerplate, they're
the credit trail for work that made this SDK possible.
