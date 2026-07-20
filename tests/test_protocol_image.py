"""Golden + structural tests for DIY frame packet building.

The golden values were proven byte-identical to the original lab implementation
(idotmatrix-api-client) before being pinned here.
"""

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from pyidotmatrix.protocol import image
from pyidotmatrix.protocol.bytes_ import MTU_SIZE_IF_ENABLED

DEMO_IMAGE = Path(__file__).parent / "demo_64.png"

# Pinned from the verified-equivalent build; guards against regressions.
GOLDEN_SHA256 = "a407fa78e50fb2d24d42cee4eb4c5fbcbacdc3cfedef3c69a8bcc8e84d2dba08"


def _flatten(packets: list[list[bytearray]]) -> bytes:
    return b"".join(bytes(p) for chunk in packets for p in chunk)


def test_demo_frame_matches_golden():
    rgb = Image.open(DEMO_IMAGE).convert("RGB").tobytes()
    packets = image.build_frame_packets(rgb)
    assert hashlib.sha256(_flatten(packets)).hexdigest() == GOLDEN_SHA256


def test_frame_chunking_shape():
    # 64x64 RGB = 12288 bytes -> 3 chunks of 4096; each chunk + 9-byte header
    # = 4105 bytes -> 9 BLE packets at the 509-byte MTU.
    rgb = bytes(64 * 64 * 3)
    packets = image.build_frame_packets(rgb)
    assert len(packets) == 3
    assert all(len(chunk) == 9 for chunk in packets)
    assert all(len(packet) <= MTU_SIZE_IF_ENABLED for chunk in packets for packet in chunk)


def test_header_encodes_length_flag_and_total_size():
    rgb = bytes(32 * 32 * 3)  # 3072 bytes -> single 4096 chunk
    packets = image.build_frame_packets(rgb)
    header = bytes(packets[0][0][:9])
    assert int.from_bytes(header[0:2], "little") == 3072 + 9  # chunk + header length
    assert header[4] == 0  # first packet flag
    assert int.from_bytes(header[5:9], "little") == 3072  # total frame size


def test_continuation_flag_set_on_later_chunks():
    rgb = bytes(64 * 64 * 3)  # multiple chunks
    packets = image.build_frame_packets(rgb)
    assert bytes(packets[0][0])[4] == 0  # first chunk
    assert bytes(packets[1][0])[4] == 2  # continuation


def test_set_diy_mode():
    assert image.build_set_diy_mode(True) == bytearray([5, 0, 4, 1, 1])
    assert image.build_set_diy_mode(False) == bytearray([5, 0, 4, 1, 0])


def test_diy_mode_named_constants_match_diyimagefun_values():
    assert image.QUIT_NOSAVE_KEEP_PREV == 0
    assert image.ENTER_CLEAR_CUR_SHOW == 1
    assert image.QUIT_STILL_CUR_SHOW == 2
    assert image.ENTER_NO_CLEAR_CUR_SHOW == 3
    # backward-compatible aliases
    assert image.DIY_MODE_DISABLE == image.QUIT_NOSAVE_KEEP_PREV
    assert image.DIY_MODE_ENABLE == image.ENTER_CLEAR_CUR_SHOW


@pytest.mark.parametrize(
    "mode",
    [
        image.QUIT_NOSAVE_KEEP_PREV,
        image.ENTER_CLEAR_CUR_SHOW,
        image.QUIT_STILL_CUR_SHOW,
        image.ENTER_NO_CLEAR_CUR_SHOW,
    ],
)
def test_set_diy_mode_accepts_all_four_modes(mode):
    assert image.build_set_diy_mode(mode=mode) == bytearray([5, 0, 4, 1, mode])


def test_set_diy_mode_rejects_unknown_mode():
    with pytest.raises(ValueError):
        image.build_set_diy_mode(mode=4)
