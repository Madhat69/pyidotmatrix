#!/usr/bin/env python3
"""Decode an Android btsnoop HCI log into annotated iDotMatrix BLE traffic.

Standard library only -- no pyshark, no Wireshark, no new dependencies. Point it
at a `btsnoop_hci.log` captured while the vendor app drove a panel and it prints
one line per ATT event, with each write matched against the packet builders in
`pyidotmatrix/protocol/`. Frames that match nothing are labelled UNKNOWN, which
is the point: unknowns are undocumented app behaviour worth chasing.

Layering, outermost first:

  btsnoop file   16-byte header, then fixed 24-byte record headers (BIG-endian)
  H4             one packet-type byte (datalink 1002 = HCI UART); 0x02 is ACL
  HCI ACL        handle + PB/BC flags, then a data length (little-endian)
  L2CAP          length + CID; PDUs fragment across ACL packets and are
                 reassembled here (CID 0x0004 = ATT is the only one kept)
  ATT            opcode + handle + value
  iDotMatrix     the device's own framing, whose frames are themselves split
                 across consecutive ATT writes once they exceed the MTU --
                 reassembled a second time, for annotation only

Usage:
    python tools/parse_btsnoop.py capture.log
    python tools/parse_btsnoop.py capture.log --stats
    python tools/parse_btsnoop.py capture.log --only writes --grep "05 00 03 01"
    python tools/parse_btsnoop.py capture.log --json > events.json
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field

# --------------------------------------------------------------------------
# btsnoop container
# --------------------------------------------------------------------------

BTSNOOP_MAGIC = b"btsnoop\x00"
BTSNOOP_HEADER_SIZE = 16
BTSNOOP_RECORD_HEADER_SIZE = 24

# btsnoop timestamps count microseconds from 0000-01-01; this is the offset of
# the unix epoch within that scale.
BTSNOOP_EPOCH_DELTA_US = 0x00DCDDB30F2F8000

DATALINK_H4 = 1002  # 0x03EA, HCI UART transport (each payload starts with H4 type)

H4_COMMAND = 0x01
H4_ACL = 0x02
H4_SCO = 0x03
H4_EVENT = 0x04

# btsnoop record flag bits.
FLAG_RECEIVED = 0x01  # 0 = host -> controller (sent), 1 = controller -> host
FLAG_COMMAND_CHANNEL = 0x02

L2CAP_CID_ATT = 0x0004
ACL_PB_CONTINUATION = 0x01


class BtsnoopError(ValueError):
    """The file is not a btsnoop capture we can decode."""


@dataclass(frozen=True)
class BtsnoopRecord:
    """One record from the capture, payload still in H4 framing."""

    original_length: int
    included_length: int
    flags: int
    cumulative_drops: int
    timestamp_us: int  # raw btsnoop scale
    payload: bytes

    @property
    def is_received(self) -> bool:
        return bool(self.flags & FLAG_RECEIVED)

    @property
    def unix_timestamp_us(self) -> int:
        return self.timestamp_us - BTSNOOP_EPOCH_DELTA_US


def parse_btsnoop_header(data: bytes) -> tuple[int, int]:
    """Returns (version, datalink). Raises BtsnoopError if the magic is wrong."""
    if len(data) < BTSNOOP_HEADER_SIZE:
        raise BtsnoopError("file is shorter than a btsnoop header")
    if data[:8] != BTSNOOP_MAGIC:
        raise BtsnoopError(f"bad magic {data[:8]!r}, expected {BTSNOOP_MAGIC!r}")
    version, datalink = struct.unpack_from(">II", data, 8)
    return version, datalink


def iter_records(data: bytes) -> Iterator[BtsnoopRecord]:
    """Yields every complete record. A truncated trailing record is dropped --
    captures pulled from a live device are routinely cut mid-write."""
    offset = BTSNOOP_HEADER_SIZE
    total = len(data)
    while offset + BTSNOOP_RECORD_HEADER_SIZE <= total:
        original, included, flags, drops, timestamp = struct.unpack_from(
            ">IIIIq", data, offset
        )
        offset += BTSNOOP_RECORD_HEADER_SIZE
        if included > total - offset:
            return  # truncated tail
        yield BtsnoopRecord(
            original_length=original,
            included_length=included,
            flags=flags,
            cumulative_drops=drops,
            timestamp_us=timestamp,
            payload=data[offset : offset + included],
        )
        offset += included


# --------------------------------------------------------------------------
# ACL / L2CAP reassembly
# --------------------------------------------------------------------------


@dataclass
class _PendingPdu:
    """An L2CAP PDU still collecting continuation fragments."""

    cid: int
    expected: int  # payload bytes declared by the L2CAP length field
    buffer: bytearray


class L2capReassembler:
    """Rebuilds L2CAP PDUs from HCI ACL fragments, per connection handle.

    An ATT write larger than the ACL buffer arrives as a first fragment (PB 00 or
    10) followed by continuations (PB 01). Without stitching them back together
    every chunked upload -- GIF, DIY frame, text -- decodes as garbage.
    """

    def __init__(self) -> None:
        self._pending: dict[int, _PendingPdu] = {}

    def push(self, acl_payload: bytes) -> list[tuple[int, int, bytes]]:
        """Feeds one ACL packet (starting at the HCI ACL header). Returns any
        PDUs completed by it, as (connection_handle, cid, payload)."""
        if len(acl_payload) < 4:
            return []
        handle_flags, data_length = struct.unpack_from("<HH", acl_payload, 0)
        handle = handle_flags & 0x0FFF
        pb = (handle_flags >> 12) & 0x03
        body = acl_payload[4 : 4 + data_length]

        if pb == ACL_PB_CONTINUATION:
            pending = self._pending.get(handle)
            if pending is None:
                return []  # continuation with no start (capture began mid-PDU)
            pending.buffer.extend(body)
        else:
            if len(body) < 4:
                return []
            l2cap_length, cid = struct.unpack_from("<HH", body, 0)
            pending = _PendingPdu(cid=cid, expected=l2cap_length, buffer=bytearray(body[4:]))
            self._pending[handle] = pending

        if len(pending.buffer) >= pending.expected:
            del self._pending[handle]
            return [(handle, pending.cid, bytes(pending.buffer[: pending.expected]))]
        return []


# --------------------------------------------------------------------------
# ATT
# --------------------------------------------------------------------------

ATT_ERROR_RESPONSE = 0x01
ATT_EXCHANGE_MTU_REQUEST = 0x02
ATT_EXCHANGE_MTU_RESPONSE = 0x03
ATT_READ_BY_TYPE_REQUEST = 0x08
ATT_READ_BY_TYPE_RESPONSE = 0x09
ATT_READ_REQUEST = 0x0A
ATT_READ_RESPONSE = 0x0B
ATT_READ_BY_GROUP_TYPE_REQUEST = 0x10
ATT_READ_BY_GROUP_TYPE_RESPONSE = 0x11
ATT_WRITE_REQUEST = 0x12
ATT_WRITE_RESPONSE = 0x13
ATT_WRITE_COMMAND = 0x52
ATT_HANDLE_VALUE_NOTIFICATION = 0x1B
ATT_HANDLE_VALUE_INDICATION = 0x1D
ATT_HANDLE_VALUE_CONFIRMATION = 0x1E

_ATT_KIND = {
    ATT_ERROR_RESPONSE: "ERROR-RSP",
    ATT_EXCHANGE_MTU_REQUEST: "MTU-REQ",
    ATT_EXCHANGE_MTU_RESPONSE: "MTU-RSP",
    0x04: "FIND-INFO-REQ",
    0x05: "FIND-INFO-RSP",
    0x06: "FIND-BY-TYPE-REQ",
    0x07: "FIND-BY-TYPE-RSP",
    ATT_READ_BY_TYPE_REQUEST: "READ-BY-TYPE-REQ",
    ATT_READ_BY_TYPE_RESPONSE: "READ-BY-TYPE-RSP",
    ATT_READ_REQUEST: "READ-REQ",
    ATT_READ_RESPONSE: "READ-RSP",
    0x0C: "READ-BLOB-REQ",
    0x0D: "READ-BLOB-RSP",
    ATT_READ_BY_GROUP_TYPE_REQUEST: "READ-BY-GROUP-REQ",
    ATT_READ_BY_GROUP_TYPE_RESPONSE: "READ-BY-GROUP-RSP",
    ATT_WRITE_REQUEST: "WRITE-REQ",
    ATT_WRITE_RESPONSE: "WRITE-RSP",
    ATT_HANDLE_VALUE_NOTIFICATION: "NOTIFY",
    ATT_HANDLE_VALUE_INDICATION: "INDICATE",
    ATT_HANDLE_VALUE_CONFIRMATION: "CONFIRM",
    ATT_WRITE_COMMAND: "WRITE-CMD",
}

_WRITE_OPCODES = frozenset({ATT_WRITE_COMMAND, ATT_WRITE_REQUEST})
_NOTIFY_OPCODES = frozenset({ATT_HANDLE_VALUE_NOTIFICATION, ATT_HANDLE_VALUE_INDICATION})

# Characteristic-declaration value layouts inside a Read By Type Response:
# properties(1) + value handle(2) + UUID(2 or 16).
_CHAR_DECL_ITEM_16BIT = 7
_CHAR_DECL_ITEM_128BIT = 21


@dataclass
class AttEvent:
    """One decoded ATT PDU, ready to print."""

    index: int
    time_us: int  # unix microseconds
    rel_time: float  # seconds since the first record
    direction: str  # TX (host -> controller) or RX
    kind: str
    opcode: int
    handle: int | None
    payload: bytes
    annotation: str = ""
    shape: str = ""

    @property
    def hex_payload(self) -> str:
        return " ".join(f"{b:02x}" for b in self.payload)

    def format_line(self, handle_names: dict[int, str] | None = None) -> str:
        if self.handle is None:
            handle_text = "----"
        else:
            name = (handle_names or {}).get(self.handle)
            handle_text = f"0x{self.handle:04x}" + (f"/{name}" if name else "")
        return (
            f"{self.rel_time:9.3f}  {self.direction}  {self.kind:<17} "
            f"{handle_text:<12} len={len(self.payload):<4} "
            f"{self.hex_payload:<80}  {self.annotation}"
        )

    def to_dict(self, handle_names: dict[int, str] | None = None) -> dict[str, object]:
        data = asdict(self)
        data["payload"] = self.hex_payload
        data["characteristic"] = (handle_names or {}).get(self.handle or -1, "")
        return data


class HandleMap:
    """Maps ATT value handles to characteristic UUIDs.

    Uses real service discovery when the capture contains it. Android often
    re-uses a cached GATT database and skips discovery entirely on reconnect, so
    `apply_heuristics` fills the gap: the handle that carries 5-byte `05 00 ...`
    notifications is fa03, and the busiest write target is fa02.
    """

    def __init__(self) -> None:
        self.uuids: dict[int, str] = {}
        self.notify_counts: Counter[int] = Counter()
        self.write_counts: Counter[int] = Counter()

    def learn_read_by_type_response(self, payload: bytes) -> None:
        """Extracts handle->UUID pairs from characteristic declarations."""
        if len(payload) < 2:
            return
        item_length = payload[0]
        if item_length not in (_CHAR_DECL_ITEM_16BIT, _CHAR_DECL_ITEM_128BIT):
            return
        # Each item is [attribute handle(2), properties(1), value handle(2), UUID].
        for start in range(1, len(payload) - item_length + 1, item_length):
            item = payload[start : start + item_length]
            value_handle = int.from_bytes(item[3:5], "little")
            uuid_bytes = item[5:]
            if len(uuid_bytes) == 2:
                uuid = f"{int.from_bytes(uuid_bytes, 'little'):04x}"
            else:  # 128-bit UUIDs travel little-endian on the wire
                reversed_uuid = uuid_bytes[::-1].hex()
                uuid = "-".join(
                    (
                        reversed_uuid[0:8],
                        reversed_uuid[8:12],
                        reversed_uuid[12:16],
                        reversed_uuid[16:20],
                        reversed_uuid[20:32],
                    )
                )
            self.uuids[value_handle] = uuid

    def short_name(self, handle: int) -> str:
        uuid = self.uuids.get(handle)
        if uuid is None:
            return ""
        if len(uuid) == 4:
            return uuid
        # 0000fa02-0000-1000-8000-00805f9b34fb -> fa02
        base = uuid.split("-")[0]
        return base[4:] if base.startswith("0000") else base

    def apply_heuristics(self) -> None:
        if self.notify_counts and not any(
            self.short_name(h) == "fa03" for h in self.notify_counts
        ):
            handle, _ = self.notify_counts.most_common(1)[0]
            self.uuids.setdefault(handle, "0000fa03-0000-1000-8000-00805f9b34fb")
        if self.write_counts and not any(
            self.short_name(h) == "fa02" for h in self.write_counts
        ):
            handle, _ = self.write_counts.most_common(1)[0]
            self.uuids.setdefault(handle, "0000fa02-0000-1000-8000-00805f9b34fb")

    def names(self) -> dict[int, str]:
        return {handle: self.short_name(handle) for handle in self.uuids}


# --------------------------------------------------------------------------
# iDotMatrix protocol classifier
#
# Every rule below mirrors a builder in pyidotmatrix/protocol/. Nothing here is
# invented: the comment on each handler names the function it decodes.
# --------------------------------------------------------------------------

Handler = Callable[[bytes], str | None]

_DIY_MODE_NAMES = {
    0: "QUIT_NOSAVE_KEEP_PREV",
    1: "ENTER_CLEAR_CUR_SHOW",
    2: "QUIT_STILL_CUR_SHOW",
    3: "ENTER_NO_CLEAR_CUR_SHOW",
}

_MOVE_TYPE_NAMES = {
    0: "NONE",
    1: "HORIZONTAL_MIRROR",
    2: "VERTICAL_MIRROR",
    3: "OVERALL_MOVEMENT",
    4: "ERASE",
}

_TEXT_MODE_NAMES = {
    0: "REPLACE",
    1: "MARQUEE",
    2: "REVERSED_MARQUEE",
    3: "VERTICAL_RISING",
    4: "VERTICAL_LOWERING",
    5: "BLINKING",
    6: "FADING",
    7: "TETRIS",
    8: "FILLING",
}

_COLOR_MODE_NAMES = {
    0: "WHITE",
    1: "RGB",
    2: "RAINBOW_1",
    3: "RAINBOW_2",
    4: "RAINBOW_3",
    5: "RAINBOW_4",
}

_CLOCK_STYLE_NAMES = {
    0: "RGB_SWIPE_OUTLINE",
    1: "CHRISTMAS_TREE",
    2: "CHECKERS",
    3: "COLOR",
    4: "HOURGLASS",
    5: "ALARM_CLOCK",
    6: "OUTLINES",
    7: "RGB_CORNERS",
}

# Status vocabulary of the 3-way status-ack family (protocol/response.py).
_STATUS_ACK_KEYS = frozenset({(0x00, 0x80), (0x05, 0x80), (0x03, 0x00), (0x01, 0x00)})
_STATUS_NAMES = {0: "FAILED", 1: "NEXT_CHUNK", 3: "SAVED"}


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


# ---- fixed-size single commands -------------------------------------------


def _brightness(p: bytes) -> str | None:
    # common.build_set_brightness -> [5, 0, 4, 128, percent]
    return f"brightness={p[4]}" if len(p) == 5 else None


def _diy_mode(p: bytes) -> str | None:
    # image.build_set_diy_mode -> [5, 0, 4, 1, mode]
    if len(p) != 5:
        return None
    return f"diy_mode={p[4]} ({_DIY_MODE_NAMES.get(p[4], '?')})"


def _set_password(p: bytes) -> str | None:
    # common.build_set_password -> [8, 0, 4, 2, 1, high, mid, low]
    return "set_password" if len(p) == 8 and p[4] == 1 else None


def _speed(p: bytes) -> str | None:
    # common.build_set_speed -> [5, 0, 3, 1, speed]
    return f"set_speed={p[4]}" if len(p) == 5 else None


def _freeze(p: bytes) -> str | None:
    # common.build_freeze_screen -> [4, 0, 3, 0]
    return "freeze_screen" if len(p) == 4 else None


def _reset(p: bytes) -> str | None:
    # common.build_reset -> 04 00 03 80
    return "reset" if len(p) == 4 else None


def _effect(p: bytes) -> str | None:
    # effect.build_show -> [6+n, 0, 3, 2, style, speed, count] + n*RGB
    if len(p) < 7:
        return None
    count = p[6]
    if len(p) != 7 + 3 * count:
        return None
    colors = " ".join(
        f"#{p[7 + 3 * i]:02x}{p[8 + 3 * i]:02x}{p[9 + 3 * i]:02x}" for i in range(count)
    )
    return f"effect style={p[4]} speed={p[5]} colors={count} [{colors}]"


def _set_time(p: bytes) -> str | None:
    # common.build_set_time -> [11, 0, 1, 128, yy, mm, dd, weekday, HH, MM, SS]
    if len(p) != 11:
        return None
    return (
        f"set_time 20{p[4]:02d}-{p[5]:02d}-{p[6]:02d} "
        f"wd={p[7]} {p[8]:02d}:{p[9]:02d}:{p[10]:02d}"
    )


def _power(p: bytes) -> str | None:
    # common.build_set_power -> [5, 0, 7, 1, on]
    return f"power={'on' if p[4] else 'off'}" if len(p) == 5 else None


def _flip(p: bytes) -> str | None:
    # common.build_set_screen_flipped -> [5, 0, 6, 128, flipped]
    return f"screen_flipped={p[4]}" if len(p) == 5 else None


def _clock(p: bytes) -> str | None:
    # clock.build_show -> [8, 0, 6, 1, flags, r, g, b]
    if len(p) != 8:
        return None
    flags = p[4]
    style = flags & 0x07
    return (
        f"clock style={style} ({_CLOCK_STYLE_NAMES.get(style, '?')}) "
        f"date={bool(flags & 0x80)} hour24={bool(flags & 0x40)} "
        f"color=#{p[5]:02x}{p[6]:02x}{p[7]:02x} flags=0x{flags:02x}"
    )


def _time_indicator_or_master_switch(p: bytes) -> str | None:
    # common.build_set_time_indicator -> [5, 0, 7, 128, enabled]
    # schedule master switch -> [5, 0, 7, 128, packed] (same shape, see below)
    if len(p) != 5:
        return None
    return f"time_indicator/schedule_master_switch={p[4]}"


def _fullscreen_color(p: bytes) -> str | None:
    # fullscreen_color.build_show_color -> [7, 0, 2, 2, r, g, b]
    return f"fullscreen_color=#{p[4]:02x}{p[5]:02x}{p[6]:02x}" if len(p) == 7 else None


def _eco(p: bytes) -> str | None:
    # eco.build_set_mode -> [10, 0, 2, 128, on, sh, sm, eh, em, brightness]
    if len(p) != 10:
        return None
    return (
        f"eco enabled={p[4]} {p[5]:02d}:{p[6]:02d}-{p[7]:02d}:{p[8]:02d} "
        f"brightness={p[9]}"
    )


def _delete_device_data(p: bytes) -> str | None:
    # common.build_delete_device_data -> [17, 0, 2, 1, 12, 0..11]
    return "delete_device_data" if len(p) == 17 and p[4] == 12 else None


def _chronograph(p: bytes) -> str | None:
    # chronograph.build_set_mode -> [5, 0, 9, 128, mode]
    return f"chronograph mode={p[4]}" if len(p) == 5 else None


def _countdown(p: bytes) -> str | None:
    # countdown.build_set_mode -> [7, 0, 8, 128, mode, minutes, seconds]
    return f"countdown mode={p[4]} {p[5]:02d}:{p[6]:02d}" if len(p) == 7 else None


def _scoreboard(p: bytes) -> str | None:
    # scoreboard.build_show -> [8, 0, 10, 128, lo1, hi1, lo2, hi2]
    if len(p) != 8:
        return None
    return f"scoreboard {p[4] | (p[5] << 8)}:{p[6] | (p[7] << 8)}"


def _mic_type(p: bytes) -> str | None:
    # music_sync.build_set_mic_type -> [6, 0, 11, 128, mic_type]
    return f"mic_type={p[4]}" if len(p) == 5 else None


def _joint(p: bytes) -> str | None:
    # common.build_set_joint -> [5, 0, 12, 128, mode]
    return f"set_joint={p[4]}" if len(p) == 5 else None


def _screen_timeout(p: bytes) -> str | None:
    # common.build_set_screen_timeout / build_read_screen_timeout
    if len(p) != 5:
        return None
    return "read_screen_timeout" if p[4] == 255 else f"screen_timeout={p[4]}"


def _rhythm(p: bytes) -> str | None:
    # music_sync.build_send_image_rhythm -> [6, 0, 0, 2, value, 1]
    # music_sync.build_stop_rhythm      -> [6, 0, 0, 2, 0, 0]
    if len(p) != 6:
        return None
    return "stop_rhythm" if p[5] == 0 else f"image_rhythm value={p[4]}"


def _verify_password(p: bytes) -> str | None:
    # common.build_verify_password -> [7, 0, 5, 2, high, mid, low]
    return "verify_password" if len(p) == 7 else None


# ---- variable-size / chunk-header commands --------------------------------


def _graffiti(p: bytes) -> str | None:
    # graffiti.build_set_pixels ->
    #   [len_lo, len_hi, 5, 1, move_type, r, g, b] + (x, y) pairs
    if len(p) < 8 or (len(p) - 8) % 2:
        return None
    pixels = (len(p) - 8) // 2
    coords = [(p[8 + 2 * i], p[9 + 2 * i]) for i in range(pixels)]
    shown = ",".join(f"({x},{y})" for x, y in coords[:6])
    if pixels > 6:
        shown += f",+{pixels - 6}"
    return (
        f"graffiti move={p[4]} ({_MOVE_TYPE_NAMES.get(p[4], '?')}) "
        f"color=#{p[5]:02x}{p[6]:02x}{p[7]:02x} pixels={pixels} [{shown}]"
    )


def _diy_frame_chunk(p: bytes) -> str | None:
    # image._build_header -> 9-byte header:
    #   [len_lo, len_hi, 0, 0, first/cont, total_size(4, LE)]
    if len(p) < 9:
        return None
    marker = {0: "first", 2: "cont"}.get(p[4])
    if marker is None:
        return None
    return (
        f"diy_frame_chunk {marker} declared={_u16(p, 0)} total={_u32(p, 5)} "
        f"data={len(p) - 9}"
    )


def _timer_chunk(p: bytes) -> str | None:
    # timer._build_header -> 24-byte header
    if len(p) < 24:
        return None
    marker = {0: "first", 2: "cont"}.get(p[12])
    if marker is None:
        return None
    return (
        f"timer_chunk {marker} num={p[4]} week=0x{p[5]:02x} {p[6]:02d}:{p[7]:02d} "
        f"duration={_u16(p, 8)}s content={p[10]} buzzer={p[11]} "
        f"total={_u32(p, 13)} crc=0x{_u32(p, 17):08x}"
    )


def _schedule_chunk(p: bytes) -> str | None:
    # schedule._build_header -> 23-byte header
    if len(p) < 23:
        return None
    marker = {0: "first", 2: "cont"}.get(p[11])
    if marker is None:
        return None
    return (
        f"schedule_chunk {marker} index={p[4]} week=0x{p[5]:02x} "
        f"{p[6]:02d}:{p[7]:02d}-{p[8]:02d}:{p[9]:02d} content={p[10]} "
        f"total={_u32(p, 12)} crc=0x{_u32(p, 16):08x}"
    )


def _gif_chunk(p: bytes) -> str | None:
    # gif._build_header -> 16-byte header:
    #   [len(2), 1, 0, first/cont, total(4), crc32(4), time_sign(2), gif_type]
    if len(p) < 16:
        return None
    marker = {0: "first", 2: "cont"}.get(p[4])
    if marker is None:
        return None
    return (
        f"gif_chunk {marker} declared={_u16(p, 0)} total={_u32(p, 5)} "
        f"crc=0x{_u32(p, 9):08x} time_sign={_u16(p, 13)} gif_type={p[15]} "
        f"data={len(p) - 16}"
    )


def _text_chunk(p: bytes) -> str | None:
    # text._build_header_32x32 / build_text_packet -> 16-byte header, then the
    # 14-byte metadata block the builders describe.
    if len(p) < 16:
        return None
    marker = {0: "first", 2: "cont"}.get(p[4])
    if marker is None:
        return None
    base = (
        f"text_chunk {marker} declared={_u16(p, 0)} total={_u32(p, 5)} "
        f"crc=0x{_u32(p, 9):08x} trailer={p[15]}"
    )
    if marker == "cont" or len(p) < 30:
        return base
    meta = p[16:30]
    family = {0: "8-row (sendTextTo832)", 1: "16/32-row (sendTextTo3232)"}.get(
        meta[2], f"?{meta[2]}"
    )
    return (
        f"{base} | chars={_u16(meta, 0)} row_family={meta[2]} ({family}) "
        f"b3={meta[3]} mode={meta[4]} ({_TEXT_MODE_NAMES.get(meta[4], '?')}) "
        f"speed={meta[5]} color_mode={meta[6]} "
        f"({_COLOR_MODE_NAMES.get(meta[6], '?')}) "
        f"fg=#{meta[7]:02x}{meta[8]:02x}{meta[9]:02x} bg_mode={meta[10]} "
        f"bg=#{meta[11]:02x}{meta[12]:02x}{meta[13]:02x}"
    )


# Dispatch on the (type, subtype) pair at payload bytes 2 and 3 -- the same two
# bytes the device echoes back in its ack.
_HANDLERS: dict[tuple[int, int], Handler] = {
    (0x00, 0x00): _diy_frame_chunk,
    (0x00, 0x02): _rhythm,
    (0x00, 0x80): _timer_chunk,
    (0x01, 0x00): _gif_chunk,
    (0x01, 0x80): _set_time,
    (0x02, 0x01): _delete_device_data,
    (0x02, 0x02): _fullscreen_color,
    (0x02, 0x80): _eco,
    (0x03, 0x00): _text_chunk,
    (0x03, 0x01): _speed,
    (0x03, 0x02): _effect,
    (0x03, 0x80): _reset,
    (0x04, 0x01): _diy_mode,
    (0x04, 0x02): _set_password,
    (0x04, 0x80): _brightness,
    (0x05, 0x01): _graffiti,
    (0x05, 0x02): _verify_password,
    (0x05, 0x80): _schedule_chunk,
    (0x06, 0x01): _clock,
    (0x06, 0x80): _flip,
    (0x07, 0x01): _power,
    (0x07, 0x80): _time_indicator_or_master_switch,
    (0x08, 0x80): _countdown,
    (0x09, 0x80): _chronograph,
    (0x0A, 0x80): _scoreboard,
    (0x0B, 0x80): _mic_type,
    (0x0C, 0x80): _joint,
    (0x0F, 0x80): _screen_timeout,
}

# (0x03, 0x00) is both the text chunk header and freeze_screen ([4, 0, 3, 0]),
# which the length field separates.
_LENGTH_OVERRIDES: dict[tuple[int, int], dict[int, Handler]] = {
    (0x03, 0x00): {4: _freeze},
}


def _effect_subframe(payload: bytes) -> str | None:
    """The effect family's bespoke re-packetization (effect.build_show_packets,
    MutilColorAgreement.getSendData): a 2-byte [chunk_len + 1, chunk_index]
    sub-header wrapping slices of the flat effect command.

    Only sub-chunk 0 carries the effect header, so only it can be identified
    with confidence; continuation sub-chunks are raw colour bytes and are left
    UNKNOWN rather than guessed at.
    """
    if len(payload) < 9 or payload[0] != len(payload) - 1 or payload[1] != 0:
        return None
    inner = payload[2:]
    if inner[1] != 0 or inner[2] != 3 or inner[3] != 2:
        return None
    return (
        f"effect_subchunk index=0 (flat_len={inner[0]} style={inner[4]} "
        f"speed={inner[5]} colors={inner[6]})"
    )


def classify_write(payload: bytes) -> tuple[str, str]:
    """Annotates one complete iDotMatrix command frame.

    Returns (annotation, shape) where shape is a coarse grouping key for --stats.
    """
    # Checked before the length guard: a CCCD write is a legitimate 2-byte PDU
    # (0x0001 = subscribe to notifications), not a truncated device command.
    if len(payload) == 2 and payload in (b"\x01\x00", b"\x02\x00", b"\x00\x00"):
        subscription = {
            b"\x01\x00": "notifications",
            b"\x02\x00": "indications",
            b"\x00\x00": "off",
        }[payload]
        return f"CCCD write: {subscription}", "CCCD"

    if len(payload) < 4:
        return f"UNKNOWN short len={len(payload)}", f"UNKNOWN len={len(payload)}"

    command_type, subtype = payload[2], payload[3]
    key = (command_type, subtype)

    override = _LENGTH_OVERRIDES.get(key, {}).get(len(payload))
    handler = override or _HANDLERS.get(key)
    if handler is not None:
        result = handler(payload)
        if result is not None:
            return result, result.split()[0]

    subframe = _effect_subframe(payload)
    if subframe is not None:
        return subframe, "effect_subchunk"

    declared = _u16(payload, 0)
    length_note = "" if declared == len(payload) else f" declared={declared}"
    return (
        f"UNKNOWN type=0x{command_type:02x} sub=0x{subtype:02x} "
        f"len={len(payload)}{length_note}",
        f"UNKNOWN type=0x{command_type:02x} sub=0x{subtype:02x}",
    )


def classify_notification(payload: bytes) -> tuple[str, str]:
    """Annotates a device notification (protocol/response.py)."""
    if len(payload) != 5 or payload[0] != 0x05 or payload[1] != 0x00:
        return (
            f"UNKNOWN notification len={len(payload)}",
            f"UNKNOWN notify len={len(payload)}",
        )
    command_type, subtype, status = payload[2], payload[3], payload[4]
    if (command_type, subtype) in _STATUS_ACK_KEYS:
        name = _STATUS_NAMES.get(status, "?")
        verdict = f"status={status} ({name})"
    else:
        verdict = f"status={status} ({'accepted' if status == 0x01 else 'rejected'})"
    return (
        f"ack type={command_type} sub={subtype} {verdict}",
        f"ack type={command_type} sub={subtype}",
    )


class ProtocolReassembler:
    """Stitches iDotMatrix frames back together across consecutive ATT writes.

    A 4096-byte upload chunk is bigger than any BLE MTU, so the app writes it as
    several ATT payloads in a row. Only the first carries the header, so
    annotating each write in isolation would leave every follow-up as UNKNOWN.
    Frames declare their own total length in bytes 0-1 (little-endian), which is
    what drives the stitching here. Annotation only -- the raw hex printed for
    each event is always the untouched ATT payload.
    """

    _MAX_FRAME = 8192  # a 4096 chunk plus the largest header, with headroom

    # A frame only splits across writes because the MTU forced it, so a genuine
    # first fragment is always MTU-sized -- hundreds of bytes. Requiring that
    # keeps short frames from swallowing the write after them: the music-sync
    # family (`21 00 01 02 00` + 16 level bytes) is 21 bytes long but puts 0x21
    # = 33 in the length field, and without this floor every second music frame
    # was mis-read as a continuation of the one before it.
    _MIN_FRAGMENT_BYTES = 64

    def __init__(self) -> None:
        self._remaining = 0
        self._label = ""
        self._part = 0

    def annotate(self, payload: bytes) -> tuple[str, str]:
        if self._remaining > 0:
            self._part += 1
            consumed = min(self._remaining, len(payload))
            self._remaining -= consumed
            tail = "" if self._remaining else ", final"
            return (
                f"cont part={self._part} of {self._label} "
                f"({len(payload)} B, {self._remaining} left{tail})",
                f"cont {self._label}",
            )

        annotation, shape = classify_write(payload)
        if len(payload) >= self._MIN_FRAGMENT_BYTES:
            declared = _u16(payload, 0)
            if len(payload) < declared <= self._MAX_FRAME:
                self._remaining = declared - len(payload)
                self._label = shape
                self._part = 1
                return f"{annotation} [frag 1, {self._remaining} B to follow]", shape
        return annotation, shape

    def reset(self) -> None:
        self._remaining = 0
        self._part = 0


# --------------------------------------------------------------------------
# Top-level decode
# --------------------------------------------------------------------------


@dataclass
class Capture:
    version: int
    datalink: int
    events: list[AttEvent] = field(default_factory=list)
    handles: HandleMap = field(default_factory=HandleMap)
    record_count: int = 0
    acl_count: int = 0
    first_time_us: int = 0
    last_time_us: int = 0


def parse_capture(data: bytes) -> Capture:
    """Decodes a whole btsnoop file into annotated ATT events."""
    version, datalink = parse_btsnoop_header(data)
    capture = Capture(version=version, datalink=datalink)
    if datalink != DATALINK_H4:
        raise BtsnoopError(
            f"unsupported datalink {datalink}, only {DATALINK_H4} (HCI UART H4) is decoded"
        )

    reassembler = L2capReassembler()
    protocol_streams: dict[int, ProtocolReassembler] = {}
    base_time: int | None = None
    index = 0

    for record in iter_records(data):
        capture.record_count += 1
        unix_us = record.unix_timestamp_us
        if base_time is None:
            base_time = unix_us
            capture.first_time_us = unix_us
        capture.last_time_us = unix_us

        if not record.payload or record.payload[0] != H4_ACL:
            continue
        capture.acl_count += 1

        for _connection, cid, pdu in reassembler.push(record.payload[1:]):
            if cid != L2CAP_CID_ATT or not pdu:
                continue
            event = _decode_att(
                pdu,
                index=index,
                unix_us=unix_us,
                rel_time=(unix_us - base_time) / 1_000_000,
                is_received=record.is_received,
                handles=capture.handles,
                protocol_streams=protocol_streams,
            )
            if event is not None:
                capture.events.append(event)
                index += 1

    capture.handles.apply_heuristics()
    return capture


def _decode_att(
    pdu: bytes,
    *,
    index: int,
    unix_us: int,
    rel_time: float,
    is_received: bool,
    handles: HandleMap,
    protocol_streams: dict[int, ProtocolReassembler],
) -> AttEvent | None:
    opcode = pdu[0]
    kind = _ATT_KIND.get(opcode, f"ATT-0x{opcode:02x}")
    direction = "RX" if is_received else "TX"
    handle: int | None = None
    value = pdu[1:]
    annotation = ""
    shape = kind

    if opcode in _WRITE_OPCODES or opcode in _NOTIFY_OPCODES:
        if len(pdu) < 3:
            return None
        handle = _u16(pdu, 1)
        value = pdu[3:]

    if opcode in _WRITE_OPCODES:
        handles.write_counts[handle or 0] += len(value)
        stream = protocol_streams.setdefault(handle or 0, ProtocolReassembler())
        annotation, shape = stream.annotate(value)
    elif opcode in _NOTIFY_OPCODES:
        handles.notify_counts[handle or 0] += 1
        annotation, shape = classify_notification(value)
    elif opcode == ATT_READ_BY_TYPE_RESPONSE:
        handles.learn_read_by_type_response(value)
        annotation = "service discovery: characteristic declarations"
    elif opcode in (ATT_EXCHANGE_MTU_REQUEST, ATT_EXCHANGE_MTU_RESPONSE):
        if len(value) >= 2:
            annotation = f"mtu={_u16(value, 0)}"
    elif opcode == ATT_ERROR_RESPONSE and len(value) >= 4:
        annotation = (
            f"error on op=0x{value[0]:02x} handle=0x{_u16(value, 1):04x} "
            f"code=0x{value[3]:02x}"
        )

    return AttEvent(
        index=index,
        time_us=unix_us,
        rel_time=rel_time,
        direction=direction,
        kind=kind,
        opcode=opcode,
        handle=handle,
        payload=value,
        annotation=annotation,
        shape=shape,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _filter_events(
    events: list[AttEvent], only: str | None, grep: str | None
) -> list[AttEvent]:
    selected = events
    if only == "writes":
        selected = [e for e in selected if e.opcode in _WRITE_OPCODES]
    elif only == "notifies":
        selected = [e for e in selected if e.opcode in _NOTIFY_OPCODES]
    if grep:
        prefix = grep.replace(" ", "").lower()
        selected = [e for e in selected if e.payload.hex().startswith(prefix)]
    return selected


def _print_stats(capture: Capture, events: list[AttEvent]) -> None:
    names = capture.handles.names()
    duration = (capture.last_time_us - capture.first_time_us) / 1_000_000

    print("=== capture ===")
    print(f"btsnoop version {capture.version}, datalink {capture.datalink}")
    print(f"records: {capture.record_count}   ACL packets: {capture.acl_count}")
    print(f"ATT events: {len(capture.events)}   after filters: {len(events)}")
    print(f"duration: {duration:.3f} s")

    print("\n=== handles ===")
    for handle in sorted(set(names) | set(capture.handles.write_counts) | set(capture.handles.notify_counts)):
        name = names.get(handle, "")
        uuid = capture.handles.uuids.get(handle, "")
        print(
            f"0x{handle:04x}  {name or '----':<6} {uuid:<40} "
            f"write_bytes={capture.handles.write_counts.get(handle, 0)} "
            f"notifies={capture.handles.notify_counts.get(handle, 0)}"
        )

    print("\n=== annotations ===")
    for shape, count in Counter(e.shape for e in events).most_common():
        print(f"{count:6d}  {shape}")

    print("\n=== write sizes ===")
    sizes = Counter(len(e.payload) for e in events if e.opcode in _WRITE_OPCODES)
    for size, count in sorted(sizes.items()):
        print(f"{size:6d} B  x{count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decode a btsnoop HCI log into annotated iDotMatrix BLE traffic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("logfile", help="path to btsnoop_hci.log")
    parser.add_argument("--json", action="store_true", help="emit events as JSON")
    parser.add_argument(
        "--stats",
        action="store_true",
        help="print a summary (handles, annotation counts, write-size histogram)",
    )
    parser.add_argument(
        "--only",
        choices=("writes", "notifies"),
        help="restrict output to host writes or device notifications",
    )
    parser.add_argument(
        "--grep",
        metavar="HEXPREFIX",
        help='keep events whose payload starts with this hex prefix (e.g. "05 00 03 01")',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    with open(args.logfile, "rb") as handle:
        data = handle.read()

    try:
        capture = parse_capture(data)
    except BtsnoopError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    events = _filter_events(capture.events, args.only, args.grep)
    names = capture.handles.names()

    if args.json:
        json.dump([event.to_dict(names) for event in events], sys.stdout, indent=1)
        sys.stdout.write("\n")
    elif args.stats:
        _print_stats(capture, events)
    else:
        for event in events:
            print(event.format_line(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
