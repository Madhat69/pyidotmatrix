"""Parser for the status notifications the device pushes on the notify characteristic.

Discovered by subscribing to fa03 (earlier work only tried to read it, which is not
permitted). For every recognized command the device sends back a 5-byte frame:

    [0x05, 0x00, command_type, command_subtype, status]

where command_type/subtype echo bytes 2-3 of the command that was sent, and status
is 0x01 (accepted) or 0x00 (rejected, e.g. a parameter out of range). Unrecognized
or malformed commands produce no notification at all.

Status-ack family (HARDWARE-CONFIRMED 2026-07-12, both members): some command
families' acks use the *same* 5-byte frame shape but a richer, 3-way status
instead of DeviceAck's plain accept/reject: 1 = send the next chunk (also
observed as the status echoed by a flat close on an empty/unsaved slot), 3 =
fully saved (also the status echoed by a flat close on a slot that already has
content), 0 = failed. Two members of this family are confirmed on hardware:
Timer's sendData/sendCloseData ([5,0,0x00,0x80,status]) and Schedule's
per-theme upload ([5,0,0x05,0x80,status]) -- the latter was previously
misparsed as a plain DeviceAck, which made a *successful* save (status=3) look
like a rejection (accepted = status==0x01 = False), logging a spurious
"device rejected command type=5 subtype=128" warning on the transport for a
command that had, in fact, saved correctly. Both behaviors worth knowing
apply to both families: a single-outer-chunk upload goes straight to
status=3 SAVED with no status=1 NEXT_CHUNK in between, and status-ack frames
can arrive DUPLICATED (the same status seen twice for one chunk) -- callers
should tolerate repeats. parse_response dispatches on the exact (type,
subtype) pairs in _STATUS_ACK_KEYS to return a StatusAck instead of a
DeviceAck; every other (type, subtype) still produces a plain DeviceAck
exactly as before -- including Schedule's master switch
([5,0,7,0x80,status]), whose observed replies are plain accept-style, not
this 3-way vocabulary, so it deliberately stays on the DeviceAck path. See
tests/test_protocol_timer_schedule.py.

Verified no other ported command collides with (0x05, 0x80): every other
builder's bytes 2-3 are a different (type, subtype) pair, and graffiti (the
only other command using type byte 5) uses the mirror mode 1-4 in the subtype
position, never 0x80, and produces no ack at all (see transport/ble.py's
_GRAFFITI_TYPE_BYTE).
"""

from dataclasses import dataclass

_RESPONSE_LENGTH = 5
_STATUS_ACCEPTED = 0x01

# (command_type, command_subtype) pairs that get the 3-way StatusAck treatment
# instead of DeviceAck's boolean accept/reject. Both confirmed on hardware
# 2026-07-12: Timer's sendData/sendCloseData (0x00, 0x80) and Schedule's
# per-theme upload (0x05, 0x80). Schedule's master switch (0x07, 0x80) is NOT
# in this set -- see module docstring.
_STATUS_ACK_KEYS = frozenset({(0x00, 0x80), (0x05, 0x80)})

# Status-ack family's 3-way status vocabulary (distinct from DeviceAck's plain
# accept/reject), hardware-confirmed for both member families.
STATUS_FAILED = 0
STATUS_NEXT_CHUNK = 1
STATUS_SAVED = 3

# Backward-compatible aliases: Timer was the first-ported member of this family
# and the constants were originally named for it alone.
TIMER_STATUS_FAILED = STATUS_FAILED
TIMER_STATUS_NEXT_CHUNK = STATUS_NEXT_CHUNK
TIMER_STATUS_SAVED = STATUS_SAVED


@dataclass(frozen=True)
class DeviceAck:
    """A decoded device acknowledgement for a single command."""

    command_type: int
    command_subtype: int
    accepted: bool
    raw: bytes


@dataclass(frozen=True)
class StatusAck:
    """A decoded status-ack-family acknowledgement (Timer sendData/sendCloseData,
    Schedule per-theme upload).

    status is one of STATUS_FAILED (0) / STATUS_NEXT_CHUNK (1) / STATUS_SAVED (3)
    -- richer than DeviceAck's boolean accept/reject, and deliberately has no
    `accepted` field so callers can't mistake "send the next chunk" (1) for
    outright success. HARDWARE-CONFIRMED 2026-07-12 for both member families: a
    single-chunk upload skips straight to status=3 SAVED (no status=1 in
    between); a flat close (Timer only) echoes the slot's current save-state
    (1 = empty/unsaved slot, 3 = slot already has saved content); and StatusAck
    frames can arrive duplicated for the same event -- callers should tolerate
    repeats.
    """

    command_type: int
    command_subtype: int
    status: int
    raw: bytes


# Backward-compatible alias: Timer was the first-ported member of this family
# and callers/tests may still import the old name.
TimerAck = StatusAck


def parse_response(data: bytes) -> DeviceAck | StatusAck | None:
    """Decodes one notification frame, or None if it isn't a recognized ack."""
    if len(data) != _RESPONSE_LENGTH or data[0] != 0x05 or data[1] != 0x00:
        return None
    command_type = data[2]
    command_subtype = data[3]
    if (command_type, command_subtype) in _STATUS_ACK_KEYS:
        return StatusAck(
            command_type=command_type,
            command_subtype=command_subtype,
            status=data[4],
            raw=bytes(data),
        )
    return DeviceAck(
        command_type=command_type,
        command_subtype=command_subtype,
        accepted=data[4] == _STATUS_ACCEPTED,
        raw=bytes(data),
    )
