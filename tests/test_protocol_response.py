"""Tests for device notification (ack) parsing.

Frame format confirmed on hardware: [0x05, 0x00, type, subtype, status],
status 0x01 = accepted, 0x00 = rejected. Unrecognized commands send nothing.
"""

from pyidotmatrix.protocol.response import parse_response


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
    from pyidotmatrix.protocol.response import STATUS_SAVED, StatusAck

    ack = parse_response(bytes.fromhex("0500030003"))
    assert isinstance(ack, StatusAck)
    assert ack.command_type == 0x03
    assert ack.command_subtype == 0x00
    assert ack.status == STATUS_SAVED


def test_gif_upload_ack_is_a_status_ack_with_its_own_vocabulary():
    """(0x01, 0x00) -- GIF upload -- joined the status-ack family 2026-07-24.

    Revised 2026-07-25 (probes/probe_gif_stored_chunk1.py): GIF speaks the SAME
    3-way vocabulary as Timer/Schedule -- 1 = NEXT_CHUNK between outer chunks,
    3 = SAVED (terminal success, also sent from chunk 1 when re-uploading the
    currently stored gif via single-slot CRC recognition), 0 = FAILED (a
    mid-stream 0 rejects that chunk and silently dooms the transfer). The
    earlier "terminal 0 = successful fresh store" reading was wrong -- those
    were silent failures. The old DeviceAck classification logged a spurious
    "device rejected command type=1 subtype=0" for every successful GIF upload.
    """
    from pyidotmatrix.protocol.response import STATUS_NEXT_CHUNK, STATUS_SAVED, StatusAck

    for status_byte, expected in ((0x01, STATUS_NEXT_CHUNK), (0x00, 0x00), (0x03, STATUS_SAVED)):
        ack = parse_response(bytes([0x05, 0x00, 0x01, 0x00, status_byte]))
        assert isinstance(ack, StatusAck)
        assert ack.command_type == 0x01
        assert ack.command_subtype == 0x00
        assert ack.status == expected
