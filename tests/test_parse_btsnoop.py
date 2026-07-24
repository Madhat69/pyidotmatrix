"""Tests for tools/parse_btsnoop.py, the btsnoop HCI capture decoder.

Every fixture is synthesized in memory: a btsnoop header plus hand-built records
whose HCI/L2CAP/ATT framing is spelled out byte by byte, so a regression in any
layer shows up as a specific failing assertion rather than a vague decode
mismatch.
"""

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import parse_btsnoop as pb  # noqa: E402

CONNECTION_HANDLE = 0x0040
WRITE_HANDLE = 0x0011  # fa02 in the real device's GATT table
NOTIFY_HANDLE = 0x0014  # fa03

# 2026-07-25T00:00:00Z, chosen so the epoch conversion has an exact expected value.
UNIX_BASE_US = 1_784_937_600_000_000


def _btsnoop_header(datalink: int = pb.DATALINK_H4) -> bytes:
    return pb.BTSNOOP_MAGIC + struct.pack(">II", 1, datalink)


def _record(payload: bytes, *, unix_us: int, received: bool) -> bytes:
    flags = pb.FLAG_RECEIVED if received else 0
    header = struct.pack(
        ">IIIIq",
        len(payload),
        len(payload),
        flags,
        0,
        unix_us + pb.BTSNOOP_EPOCH_DELTA_US,
    )
    return header + payload


def _acl(l2cap_payload: bytes, *, first: bool = True, l2cap_length: int | None = None) -> bytes:
    """One H4 ACL packet. `first` picks PB=00 (start) vs PB=01 (continuation).

    For a start fragment the L2CAP header is prepended; `l2cap_length` overrides
    the declared length so a fragmented PDU can promise more than it carries.
    """
    if first:
        declared = len(l2cap_payload) if l2cap_length is None else l2cap_length
        body = struct.pack("<HH", declared, pb.L2CAP_CID_ATT) + l2cap_payload
        handle_flags = CONNECTION_HANDLE  # PB = 00, first fragment
    else:
        body = l2cap_payload
        handle_flags = CONNECTION_HANDLE | (pb.ACL_PB_CONTINUATION << 12)
    return bytes([pb.H4_ACL]) + struct.pack("<HH", handle_flags, len(body)) + body


def _write_command(handle: int, value: bytes) -> bytes:
    return struct.pack("<BH", pb.ATT_WRITE_COMMAND, handle) + value


def _notification(handle: int, value: bytes) -> bytes:
    return struct.pack("<BH", pb.ATT_HANDLE_VALUE_NOTIFICATION, handle) + value


@pytest.fixture
def capture_bytes() -> bytes:
    """Three events: a brightness write, a two-fragment write, and an ack."""
    brightness = _write_command(WRITE_HANDLE, bytes([5, 0, 4, 128, 60]))

    # A 40-byte graffiti frame written as one ATT PDU split across two ACL
    # fragments -- the reassembly case that chunked uploads hit constantly.
    graffiti = bytes([40, 0, 5, 1, 0, 255, 0, 0]) + bytes(range(32))
    assert len(graffiti) == 40
    fragmented = _write_command(WRITE_HANDLE, graffiti)
    split_at = 20

    ack = _notification(NOTIFY_HANDLE, bytes([0x05, 0x00, 0x04, 0x80, 0x01]))

    return b"".join(
        (
            _btsnoop_header(),
            _record(_acl(brightness), unix_us=UNIX_BASE_US, received=False),
            _record(
                _acl(fragmented[:split_at], l2cap_length=len(fragmented)),
                unix_us=UNIX_BASE_US + 500_000,
                received=False,
            ),
            _record(
                _acl(fragmented[split_at:], first=False),
                unix_us=UNIX_BASE_US + 500_100,
                received=False,
            ),
            _record(_acl(ack), unix_us=UNIX_BASE_US + 2_250_000, received=True),
        )
    )


class TestContainer:
    def test_header_round_trip(self) -> None:
        version, datalink = pb.parse_btsnoop_header(_btsnoop_header())
        assert (version, datalink) == (1, pb.DATALINK_H4)

    def test_bad_magic_rejected(self) -> None:
        with pytest.raises(pb.BtsnoopError, match="bad magic"):
            pb.parse_btsnoop_header(b"notsnoop" + bytes(8))

    def test_short_file_rejected(self) -> None:
        with pytest.raises(pb.BtsnoopError):
            pb.parse_btsnoop_header(b"btsnoop\x00")

    def test_unsupported_datalink_rejected(self) -> None:
        with pytest.raises(pb.BtsnoopError, match="unsupported datalink"):
            pb.parse_capture(_btsnoop_header(datalink=1001))

    def test_truncated_trailing_record_dropped(self, capture_bytes: bytes) -> None:
        records = list(pb.iter_records(capture_bytes[:-5]))
        assert len(records) == 3  # the fourth record's payload is incomplete

    def test_timestamp_converts_to_unix_microseconds(self, capture_bytes: bytes) -> None:
        first = next(iter(pb.iter_records(capture_bytes)))
        assert first.unix_timestamp_us == UNIX_BASE_US
        assert first.timestamp_us == UNIX_BASE_US + pb.BTSNOOP_EPOCH_DELTA_US

    def test_direction_flag(self, capture_bytes: bytes) -> None:
        records = list(pb.iter_records(capture_bytes))
        assert [r.is_received for r in records] == [False, False, False, True]


class TestReassembly:
    def test_fragmented_pdu_is_stitched_in_order(self, capture_bytes: bytes) -> None:
        capture = pb.parse_capture(capture_bytes)
        graffiti = capture.events[1]
        assert len(graffiti.payload) == 40
        assert graffiti.payload[:8] == bytes([40, 0, 5, 1, 0, 255, 0, 0])
        assert graffiti.payload[8:] == bytes(range(32))

    def test_continuation_without_a_start_is_ignored(self) -> None:
        reassembler = pb.L2capReassembler()
        assert reassembler.push(_acl(b"\x01\x02", first=False)[1:]) == []

    def test_events_are_in_capture_order(self, capture_bytes: bytes) -> None:
        capture = pb.parse_capture(capture_bytes)
        assert [e.index for e in capture.events] == [0, 1, 2]
        rel_times = [e.rel_time for e in capture.events]
        assert rel_times == sorted(rel_times)
        assert rel_times[0] == pytest.approx(0.0)
        # A reassembled PDU is timestamped at its LAST fragment (0.5001), not
        # its first (0.5) -- that is when the device actually had the command.
        assert rel_times[1] == pytest.approx(0.5001)
        assert rel_times[2] == pytest.approx(2.25)


class TestDecodedEvents:
    def test_event_kinds_and_directions(self, capture_bytes: bytes) -> None:
        capture = pb.parse_capture(capture_bytes)
        assert [(e.direction, e.kind) for e in capture.events] == [
            ("TX", "WRITE-CMD"),
            ("TX", "WRITE-CMD"),
            ("RX", "NOTIFY"),
        ]

    def test_handles_are_decoded(self, capture_bytes: bytes) -> None:
        capture = pb.parse_capture(capture_bytes)
        assert [e.handle for e in capture.events] == [
            WRITE_HANDLE,
            WRITE_HANDLE,
            NOTIFY_HANDLE,
        ]

    def test_annotations(self, capture_bytes: bytes) -> None:
        capture = pb.parse_capture(capture_bytes)
        assert capture.events[0].annotation == "brightness=60"
        assert "graffiti move=0" in capture.events[1].annotation
        assert "pixels=16" in capture.events[1].annotation
        assert capture.events[2].annotation == "ack type=4 sub=128 status=1 (accepted)"

    def test_hex_payload_is_complete_and_spaced(self, capture_bytes: bytes) -> None:
        capture = pb.parse_capture(capture_bytes)
        assert capture.events[0].hex_payload == "05 00 04 80 3c"
        assert len(capture.events[1].hex_payload.split()) == 40

    def test_heuristic_handle_map(self, capture_bytes: bytes) -> None:
        capture = pb.parse_capture(capture_bytes)
        names = capture.handles.names()
        assert names[WRITE_HANDLE] == "fa02"
        assert names[NOTIFY_HANDLE] == "fa03"


class TestClassifyWrite:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (bytes([5, 0, 4, 128, 100]), "brightness=100"),
            (bytes([5, 0, 3, 1, 42]), "set_speed=42"),
            (bytes([5, 0, 7, 1, 1]), "power=on"),
            (bytes([5, 0, 7, 1, 0]), "power=off"),
            (bytes([5, 0, 6, 128, 1]), "screen_flipped=1"),
            (bytes([4, 0, 3, 0]), "freeze_screen"),
            (bytes([4, 0, 3, 128]), "reset"),
            (bytes([5, 0, 4, 1, 3]), "diy_mode=3 (ENTER_NO_CLEAR_CUR_SHOW)"),
            (bytes([7, 0, 2, 2, 1, 2, 3]), "fullscreen_color=#010203"),
            (bytes([5, 0, 15, 128, 255]), "read_screen_timeout"),
            (bytes([5, 0, 15, 128, 30]), "screen_timeout=30"),
            (bytes([7, 0, 8, 128, 1, 5, 30]), "countdown mode=1 05:30"),
            (bytes([5, 0, 9, 128, 2]), "chronograph mode=2"),
            (bytes([6, 0, 0, 2, 0, 0]), "stop_rhythm"),
            (bytes([6, 0, 0, 2, 7, 1]), "image_rhythm value=7"),
        ],
    )
    def test_fixed_commands(self, payload: bytes, expected: str) -> None:
        annotation, _shape = pb.classify_write(payload)
        assert annotation == expected

    def test_set_time(self) -> None:
        annotation, _ = pb.classify_write(bytes([11, 0, 1, 128, 26, 7, 25, 6, 13, 45, 9]))
        assert annotation == "set_time 2026-07-25 wd=6 13:45:09"

    def test_effect(self) -> None:
        payload = bytes([9, 0, 3, 2, 4, 90, 3, 255, 0, 0, 0, 255, 0, 0, 0, 255])
        annotation, shape = pb.classify_write(payload)
        assert annotation.startswith("effect style=4 speed=90 colors=3")
        assert "#ff0000 #00ff00 #0000ff" in annotation
        assert shape == "effect"

    def test_clock_flags(self) -> None:
        annotation, _ = pb.classify_write(bytes([8, 0, 6, 1, 0xC5, 255, 255, 255]))
        assert "style=5 (ALARM_CLOCK)" in annotation
        assert "date=True hour24=True" in annotation

    def test_eco(self) -> None:
        annotation, _ = pb.classify_write(bytes([10, 0, 2, 128, 1, 22, 30, 7, 0, 20]))
        assert annotation == "eco enabled=1 22:30-07:00 brightness=20"

    def test_graffiti_mirror_mode(self) -> None:
        payload = bytes([12, 0, 5, 1, 1, 10, 20, 30, 3, 4, 5, 6])
        annotation, _ = pb.classify_write(payload)
        assert "move=1 (HORIZONTAL_MIRROR)" in annotation
        assert "color=#0a141e pixels=2 [(3,4),(5,6)]" in annotation

    def test_gif_chunk_header(self) -> None:
        payload = (
            bytes([0x10, 0x10, 1, 0, 0])
            + (4096).to_bytes(4, "little")
            + (0xDEADBEEF).to_bytes(4, "little")
            + b"\x00\x00"
            + bytes([12])
        )
        annotation, shape = pb.classify_write(payload)
        assert "gif_chunk first" in annotation
        assert "total=4096" in annotation
        assert "crc=0xdeadbeef" in annotation
        assert "gif_type=12" in annotation
        assert shape == "gif_chunk"

    def test_diy_frame_chunk_header(self) -> None:
        payload = bytes([0x09, 0x0C, 0, 0, 2]) + (3072).to_bytes(4, "little")
        annotation, _ = pb.classify_write(payload)
        assert "diy_frame_chunk cont" in annotation
        assert "total=3072" in annotation

    def test_text_chunk_header_reports_row_family(self) -> None:
        metadata = bytes([11, 0, 1, 1, 1, 95, 0, 255, 255, 255, 0, 0, 0, 0])
        payload = (
            bytes([30, 0, 3, 0, 0])
            + (14).to_bytes(4, "little")
            + (1).to_bytes(4, "little")
            + b"\x00\x00"
            + bytes([12])
            + metadata
        )
        annotation, _ = pb.classify_write(payload)
        assert "text_chunk first" in annotation
        assert "chars=11" in annotation
        assert "row_family=1 (16/32-row (sendTextTo3232))" in annotation
        assert "mode=1 (MARQUEE) speed=95" in annotation

    def test_effect_subchunk_framing(self) -> None:
        flat = bytes([9, 0, 3, 2, 4, 90, 3]) + bytes(9)
        payload = bytes([len(flat) + 1, 0]) + flat
        annotation, shape = pb.classify_write(payload)
        assert annotation.startswith("effect_subchunk index=0")
        assert "style=4 speed=90 colors=3" in annotation
        assert shape == "effect_subchunk"

    def test_unknown_frame_reports_type_and_subtype(self) -> None:
        annotation, shape = pb.classify_write(bytes([5, 0, 0x77, 0x66, 1]))
        assert annotation == "UNKNOWN type=0x77 sub=0x66 len=5"
        assert shape == "UNKNOWN type=0x77 sub=0x66"

    def test_unknown_shape_groups_across_values(self) -> None:
        _, first = pb.classify_write(bytes([5, 0, 0x77, 0x66, 1]))
        _, second = pb.classify_write(bytes([6, 0, 0x77, 0x66, 1, 2]))
        assert first == second  # --stats groups both under one shape

    def test_short_payload(self) -> None:
        annotation, _ = pb.classify_write(b"\x01")
        assert annotation.startswith("UNKNOWN short")


class TestClassifyNotification:
    def test_plain_ack(self) -> None:
        annotation, shape = pb.classify_notification(bytes([5, 0, 4, 128, 1]))
        assert annotation == "ack type=4 sub=128 status=1 (accepted)"
        assert shape == "ack type=4 sub=128"

    def test_plain_nack(self) -> None:
        annotation, _ = pb.classify_notification(bytes([5, 0, 5, 2, 0]))
        assert annotation == "ack type=5 sub=2 status=0 (rejected)"

    @pytest.mark.parametrize(
        ("key", "status", "name"),
        [
            ((0x00, 0x80), 1, "NEXT_CHUNK"),
            ((0x05, 0x80), 3, "SAVED"),
            ((0x03, 0x00), 3, "SAVED"),
            ((0x01, 0x00), 0, "FAILED"),
        ],
    )
    def test_status_ack_family(self, key: tuple[int, int], status: int, name: str) -> None:
        annotation, _ = pb.classify_notification(bytes([5, 0, key[0], key[1], status]))
        assert f"({name})" in annotation

    def test_non_ack_notification(self) -> None:
        annotation, _ = pb.classify_notification(bytes([1, 2, 3]))
        assert annotation.startswith("UNKNOWN notification")


class TestProtocolReassembler:
    def test_multi_write_frame_is_labelled(self) -> None:
        stream = pb.ProtocolReassembler()
        header = bytes([0x10, 0x10, 1, 0, 0]) + bytes(11)  # declares 4112 bytes
        first, shape = stream.annotate(header + bytes(493))
        assert shape == "gif_chunk"
        assert "frag 1" in first
        assert "3603 B to follow" in first

        second, second_shape = stream.annotate(bytes(3603))
        assert "cont part=2" in second
        assert "final" in second
        assert second_shape == "cont gif_chunk"

        # Back to normal classification once the frame is complete.
        third, _ = stream.annotate(bytes([5, 0, 4, 128, 10]))
        assert third == "brightness=10"

    def test_short_frame_with_oversized_length_field_is_not_a_fragment(self) -> None:
        """The music-sync family is 21 bytes but declares 0x21 = 33. Treating
        that as a fragment made every second frame vanish into a continuation.
        """
        stream = pb.ProtocolReassembler()
        frame = bytes([0x21, 0x00, 0x01, 0x02, 0x00]) + bytes(16)
        for _ in range(3):
            annotation, shape = stream.annotate(frame)
            assert shape == "UNKNOWN type=0x01 sub=0x02"
            assert "frag" not in annotation
            assert "cont" not in annotation

    def test_self_sized_frames_never_start_a_fragment(self) -> None:
        stream = pb.ProtocolReassembler()
        for _ in range(3):
            annotation, _ = stream.annotate(bytes([5, 0, 4, 128, 55]))
            assert annotation == "brightness=55"


class TestCli:
    def test_default_output(self, capture_bytes: bytes, tmp_path, capsys) -> None:
        log = tmp_path / "capture.log"
        log.write_bytes(capture_bytes)
        assert pb.main([str(log)]) == 0
        out = capsys.readouterr().out
        assert "05 00 04 80 3c" in out
        assert "brightness=60" in out
        assert "fa02" in out and "fa03" in out
        assert len(out.strip().splitlines()) == 3

    def test_only_notifies(self, capture_bytes: bytes, tmp_path, capsys) -> None:
        log = tmp_path / "capture.log"
        log.write_bytes(capture_bytes)
        assert pb.main([str(log), "--only", "notifies"]) == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 1
        assert "NOTIFY" in lines[0]

    def test_grep_hex_prefix_ignores_spacing(self, capture_bytes: bytes, tmp_path, capsys) -> None:
        log = tmp_path / "capture.log"
        log.write_bytes(capture_bytes)
        assert pb.main([str(log), "--grep", "05 00 04 80"]) == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 2  # the brightness write and its ack share the prefix

    def test_json_output(self, capture_bytes: bytes, tmp_path, capsys) -> None:
        log = tmp_path / "capture.log"
        log.write_bytes(capture_bytes)
        assert pb.main([str(log), "--json", "--only", "writes"]) == 0
        events = json.loads(capsys.readouterr().out)
        assert len(events) == 2
        assert events[0]["payload"] == "05 00 04 80 3c"
        assert events[0]["characteristic"] == "fa02"
        assert events[0]["annotation"] == "brightness=60"

    def test_stats_output(self, capture_bytes: bytes, tmp_path, capsys) -> None:
        log = tmp_path / "capture.log"
        log.write_bytes(capture_bytes)
        assert pb.main([str(log), "--stats"]) == 0
        out = capsys.readouterr().out
        assert "ATT events: 3" in out
        assert "duration: 2.250 s" in out
        assert "brightness" in out
        assert "5 B  x1" in out

    def test_bad_capture_exits_nonzero(self, tmp_path, capsys) -> None:
        log = tmp_path / "bad.log"
        log.write_bytes(b"notsnoop" + bytes(8))
        assert pb.main([str(log)]) == 2
        assert "bad magic" in capsys.readouterr().err


class TestCccd:
    """A CCCD subscribe is a 2-byte write and must not read as a truncated command."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (b"\x01\x00", "CCCD write: notifications"),
            (b"\x02\x00", "CCCD write: indications"),
            (b"\x00\x00", "CCCD write: off"),
        ],
    )
    def test_cccd_writes(self, value: bytes, expected: str) -> None:
        annotation, shape = pb.classify_write(value)
        assert annotation == expected
        assert shape == "CCCD"
