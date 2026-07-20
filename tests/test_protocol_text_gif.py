"""Golden + structural tests for text and GIF builders (Pillow-based).

Hashes were proven byte-identical to the lab implementation before pinning.
"""

import hashlib
import zlib
from pathlib import Path

from pyidotmatrix.imaging import ResizeMode
from pyidotmatrix.protocol import gif, text

# Test fixtures bundled with the driver's tests.
FIXTURES = Path(__file__).parent
FONT = FIXTURES / "Rain-DRM3.otf"
GIF = FIXTURES / "demo.gif"

# Note: the GIF hash depends on Pillow's encoder, so it is pinned per Pillow
# version. Byte-for-byte parity with the lab was proven at the algorithm level
# (same code + same Pillow -> identical output).
TEXT_HI_SHA256 = "5f4215fba06e657ca70d3d2831ce2021d2175244cd0906c5e559dbbc8e2e14b5"
GIF_PACKETS_SHA256 = "c101b700bdab4d752b6cd064f1e778b902737ed1bd8e3a92ecfb62e353f53b12"


def test_text_matches_golden():
    payload = text.build_text_packet("HI", str(FONT), 16, text.MODE_MARQUEE, 95, text.COLOR_WHITE, (255, 255, 255), None)
    assert hashlib.sha256(bytes(payload)).hexdigest() == TEXT_HI_SHA256


def test_text_header_crc_matches_body():
    payload = text.build_text_packet("HI", str(FONT))
    body = bytes(payload[16:])
    assert int.from_bytes(payload[0:2], "little") == len(payload)  # total length
    assert int.from_bytes(payload[5:9], "little") == len(body)     # body length
    assert int.from_bytes(payload[9:13], "little") == zlib.crc32(body)  # body CRC


def _flatten(packets):
    return b"".join(bytes(p) for chunk in packets for p in chunk)


def test_text_32x32_differs_from_generic_only_at_row_class_byte():
    """SOURCE-CONFIRMED from TextAgreement.sendTextTo3232 (decompiled APK,
    com.tech.pyidotmatrix.core.data.TextAgreement, ~line 1076-1259) vs
    sendTextTo832 (~line 130-294). This is the money finding: the two
    senders' 14-byte metadata blocks are byte-identical except index 2 --
    sendTextTo832 (this driver's legacy build_text_packet) writes 0, while
    sendTextTo3232 (and sendTextTo1616) write 1, a "row-class" flag meaning
    "16-or-32-row glyph family" vs "8-row family". Everything else -- 16px-
    wide/32px-tall glyph cells, the 0x05 char-separator tag, LE fields, outer
    16-byte chunk-header layout -- was already correct in this driver's
    existing generic builder, which is why porting sendTextTo3232 reduces to
    flipping this single byte. The device NACKed the generic packet on a real
    32x32 panel (probe 2026-07-19); hardware verification of this fix is
    pending (queued right after this lands).
    """
    generic = bytes(text.build_text_packet("HI", str(FONT)))
    flat = _flatten(text.build_text_packet_32x32("HI", str(FONT)))

    generic_body, flat_body = generic[16:], flat[16:]
    assert len(generic_body) == len(flat_body)
    assert [i for i in range(len(flat_body)) if flat_body[i] != generic_body[i]] == [2]
    assert generic_body[2] == 0
    assert flat_body[2] == 1


def test_text_32x32_header_crc_matches_body():
    packets = text.build_text_packet_32x32("HI", str(FONT))
    assert len(packets) == 1 and len(packets[0]) == 1  # short text: one chunk, one BLE packet
    payload = bytes(packets[0][0])
    header, body = payload[:16], payload[16:]
    assert int.from_bytes(header[0:2], "little") == len(payload)
    assert int.from_bytes(header[5:9], "little") == len(body)
    assert int.from_bytes(header[9:13], "little") == zlib.crc32(body)
    assert (header[2], header[3]) == (3, 0)  # outer type/subtype, same as build_text_packet
    assert header[13:15] == b"\x00\x00"
    assert header[15] == 12


def test_text_32x32_pure_black_foreground_bumped_to_blue_one():
    """SOURCE-CONFIRMED: every sendTextTo* variant in the decompile (e.g.
    TextAgreement.java ~line 1202-1205) rewrites a pure-black (0,0,0)
    foreground to (0,0,1) on the wire -- an invisible-text guard in the
    vendor app. The guard only fires when both red and green are 0; any other
    color, including a blue-tinted "black", passes through untouched.
    """
    payload = bytes(text.build_text_packet_32x32("A", str(FONT), color=(0, 0, 0))[0][0])
    metadata = payload[16:30]
    assert metadata[7:10] == bytes([0, 0, 1])  # fg RGB


def test_text_32x32_char_count_is_len_text():
    payload = bytes(text.build_text_packet_32x32("HELLO", str(FONT))[0][0])
    metadata = payload[16:30]
    assert int.from_bytes(metadata[0:2], "little") == len("HELLO")


def test_gif_packets_match_golden():
    data = gif.adapt_gif(str(GIF), 32, ResizeMode.FIT, True, (0, 0, 0), None)
    packets = gif.build_packets(data, gif.GIF_TYPE_NO_TIME_SIGNATURE, 1)
    flat = b"".join(bytes(p) for chunk in packets for p in chunk)
    assert hashlib.sha256(flat).hexdigest() == GIF_PACKETS_SHA256


def test_gif_rejects_empty():
    import pytest
    with pytest.raises(ValueError):
        gif.build_packets(b"")


def _frames(count):
    from PIL import Image
    return [Image.new("P", (8, 8)) for _ in range(count)]


def test_frame_count_capped_even_within_duration_limit():
    # 100 frames at 16ms = 1.6s total: inside the duration limit but over the
    # 64-frame device ceiling. The cap must apply regardless.
    frames, duration = gif._limit_frames(_frames(1)[0], _frames(100), 16)
    assert len(frames) <= gif.MAX_FRAME_COUNT
    assert duration == 16


def test_single_frame_never_duplicated():
    # One frame at 3000ms exceeds the duration limit but must pass through as-is.
    frames, _ = gif._limit_frames(_frames(1)[0], _frames(1), 3000)
    assert len(frames) == 1


def test_duration_limit_still_samples_multi_frame():
    frames, _ = gif._limit_frames(_frames(1)[0], _frames(30), 200)  # 6s total
    assert 2 <= len(frames) < 30
