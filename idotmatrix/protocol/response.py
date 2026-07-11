"""Parser for the status notifications the device pushes on the notify characteristic.

Discovered by subscribing to fa03 (earlier work only tried to read it, which is not
permitted). For every recognized command the device sends back a 5-byte frame:

    [0x05, 0x00, command_type, command_subtype, status]

where command_type/subtype echo bytes 2-3 of the command that was sent, and status
is 0x01 (accepted) or 0x00 (rejected, e.g. a parameter out of range). Unrecognized
or malformed commands produce no notification at all.
"""

from dataclasses import dataclass

_RESPONSE_LENGTH = 5
_STATUS_ACCEPTED = 0x01


@dataclass(frozen=True)
class DeviceAck:
    """A decoded device acknowledgement for a single command."""

    command_type: int
    command_subtype: int
    accepted: bool
    raw: bytes


def parse_response(data: bytes) -> DeviceAck | None:
    """Decodes one notification frame, or None if it isn't a recognized ack."""
    if len(data) != _RESPONSE_LENGTH or data[0] != 0x05 or data[1] != 0x00:
        return None
    return DeviceAck(
        command_type=data[2],
        command_subtype=data[3],
        accepted=data[4] == _STATUS_ACCEPTED,
        raw=bytes(data),
    )
