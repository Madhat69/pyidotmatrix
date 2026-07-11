"""Parser for the status notifications the device pushes on the notify characteristic.

Discovered by subscribing to fa03 (earlier work only tried to read it, which is not
permitted). For every recognized command the device sends back a 5-byte frame:

    [0x05, 0x00, command_type, command_subtype, status]

where command_type/subtype echo bytes 2-3 of the command that was sent, and status
is 0x01 (accepted) or 0x00 (rejected, e.g. a parameter out of range). Unrecognized
or malformed commands produce no notification at all.

Timer (HARDWARE-CONFIRMED 2026-07-12): Timer's sendData/sendCloseData acks use
the *same* 5-byte frame shape but a richer, 3-way status: 1 = send the next
chunk (also observed as the status echoed by a flat close on an empty/unsaved
slot), 3 = fully saved (also the status echoed by a flat close on a slot that
already has content), 0 = failed. All three values are now hardware-observed,
not just decompile-derived. Two behaviors worth knowing: a single-outer-chunk
upload goes straight to status=3 SAVED with no status=1 NEXT_CHUNK in between,
and TimerAck frames can arrive DUPLICATED (the same status seen twice for one
chunk) -- callers should tolerate repeats. Timer always sends
command_type=0x00/command_subtype=0x80 in bytes 2-3, a combination no other
ported command uses (checked: every other builder's bytes 2-3 are a different
pair), so parse_response dispatches on that exact pair to return a TimerAck
instead of a DeviceAck -- every other (type, subtype) still produces a plain
DeviceAck exactly as before. Schedule's acks ([5,0,7,0x80,status] for
masterSwitch, [5,0,5,0x80,status] per-theme) use type=7/type=5 respectively, so
they already fall through to the normal DeviceAck path unchanged -- see
tests/test_protocol_timer_schedule.py.
"""

from dataclasses import dataclass

_RESPONSE_LENGTH = 5
_STATUS_ACCEPTED = 0x01

# Timer ack family: command_type/command_subtype bytes unique to Timer commands
# (build_timer_close / build_timer_data_packets both send 0x00, 0x80 in bytes 2-3).
_TIMER_ACK_TYPE = 0x00
_TIMER_ACK_SUBTYPE = 0x80

# Timer's 3-way status vocabulary (distinct from DeviceAck's plain accept/reject).
TIMER_STATUS_FAILED = 0
TIMER_STATUS_NEXT_CHUNK = 1
TIMER_STATUS_SAVED = 3


@dataclass(frozen=True)
class DeviceAck:
    """A decoded device acknowledgement for a single command."""

    command_type: int
    command_subtype: int
    accepted: bool
    raw: bytes


@dataclass(frozen=True)
class TimerAck:
    """A decoded Timer-family acknowledgement (sendData / sendCloseData).

    status is one of TIMER_STATUS_FAILED (0) / TIMER_STATUS_NEXT_CHUNK (1) /
    TIMER_STATUS_SAVED (3) -- richer than DeviceAck's boolean accept/reject, and
    deliberately has no `accepted` field so callers can't mistake "send the next
    chunk" (1) for outright success. HARDWARE-CONFIRMED 2026-07-12: a
    single-chunk upload skips straight to status=3 SAVED (no status=1 in
    between); a flat close's status echoes the slot's current save-state
    (1 = empty/unsaved slot, 3 = slot already has saved content); and TimerAck
    frames can arrive duplicated for the same event.
    """

    command_type: int
    command_subtype: int
    status: int
    raw: bytes


def parse_response(data: bytes) -> DeviceAck | TimerAck | None:
    """Decodes one notification frame, or None if it isn't a recognized ack."""
    if len(data) != _RESPONSE_LENGTH or data[0] != 0x05 or data[1] != 0x00:
        return None
    command_type = data[2]
    command_subtype = data[3]
    if command_type == _TIMER_ACK_TYPE and command_subtype == _TIMER_ACK_SUBTYPE:
        return TimerAck(
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
