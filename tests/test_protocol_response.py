"""Tests for device notification (ack) parsing.

Frame format confirmed on hardware: [0x05, 0x00, type, subtype, status],
status 0x01 = accepted, 0x00 = rejected. Unrecognized commands send nothing.
"""

from idotmatrix.protocol.response import parse_response


def test_parses_accepted_ack():
    ack = parse_response(bytes.fromhex("0500048001"))  # brightness accepted
    assert ack is not None
    assert ack.command_type == 0x04
    assert ack.command_subtype == 0x80
    assert ack.accepted is True


def test_parses_rejected_ack():
    ack = parse_response(bytes.fromhex("0500048000"))  # brightness out of range
    assert ack is not None
    assert ack.accepted is False


def test_rejects_wrong_length():
    assert parse_response(bytes.fromhex("050004")) is None
    assert parse_response(bytes.fromhex("050004800100")) is None


def test_rejects_wrong_prefix():
    assert parse_response(bytes.fromhex("0600048001")) is None
    assert parse_response(bytes.fromhex("0501048001")) is None


def test_text_upload_ack_is_a_status_ack_not_a_boolean_reject():
    """(0x03, 0x00) -- text upload -- speaks the 3-way StatusAck vocabulary.

    Hardware-captured 2026-07-20 (32x32 panel, A/B with both text builders):
    the reply to a text upload is [05 00 03 00 03] -- status 3 = SAVED. The
    old DeviceAck classification read that as accepted=False and logged a
    spurious "device rejected", which mis-drove a "text is broken on 32x32"
    diagnosis on 2026-07-19. Same trap as Schedule's per-theme ack before it.
    """
    from idotmatrix.protocol.response import STATUS_SAVED, StatusAck

    ack = parse_response(bytes.fromhex("0500030003"))
    assert isinstance(ack, StatusAck)
    assert ack.command_type == 0x03
    assert ack.command_subtype == 0x00
    assert ack.status == STATUS_SAVED
