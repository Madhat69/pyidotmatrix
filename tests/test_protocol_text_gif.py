"""Golden + structural tests for text and GIF builders (Pillow-based).

Hashes were proven byte-identical to the lab implementation before pinning.
"""

import hashlib
import io
import sys
import zlib
from pathlib import Path

import pytest
from PIL import GifImagePlugin, Image

from pyidotmatrix.imaging import ResizeMode
from pyidotmatrix.protocol import gif, text

# Test fixtures bundled with the driver's tests.
FIXTURES = Path(__file__).parent
FONT = FIXTURES / "Rain-DRM3.otf"
GIF = FIXTURES / "demo.gif"

# Note: the GIF hash depends on Pillow's encoder, so it is pinned per Pillow
# version AND per platform (Windows -- see the skip in its test). Byte-for-byte
# parity with the lab was proven at the algorithm level (same code + same
# Pillow -> identical output).
TEXT_HI_SHA256 = "5f4215fba06e657ca70d3d2831ce2021d2175244cd0906c5e559dbbc8e2e14b5"
GIF_PACKETS_SHA256 = "c101b700bdab4d752b6cd064f1e778b902737ed1bd8e3a92ecfb62e353f53b12"


def test_text_matches_golden():
    payload = text.build_text_packet(
        "HI", str(FONT), 16, text.MODE_MARQUEE, 95, text.COLOR_WHITE, (255, 255, 255), None
    )
    assert hashlib.sha256(bytes(payload)).hexdigest() == TEXT_HI_SHA256


def test_text_header_crc_matches_body():
    payload = text.build_text_packet("HI", str(FONT))
    body = bytes(payload[16:])
    assert int.from_bytes(payload[0:2], "little") == len(payload)  # total length
    assert int.from_bytes(payload[5:9], "little") == len(body)  # body length
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


def test_text_32x32_8x16_glyph_branch_matches_captured_structure():
    """CAPTURE-DERIVED 2026-07-25 (vendor-app HCI capture, decoded with
    pyidotmatrix/btsnoop.py): the app drove our panel with an 8x16 glyph cell
    -- 16 bytes per glyph, each preceded by separator tag 0x02 (NOT the 6 this
    driver's RE notes predicted for non-64-byte glyphs), same row-major
    LSB-first bit order, same 16-byte header and metadata byte 2 = 1.

    Metadata field values in the captured frame: char_count u16 LE, mode 0
    (REPLACE), speed 0, color_mode 1 (RGB) followed by the RGB bytes -- all
    caller-supplied here, so this test pins them explicitly.
    """
    payload = bytes(
        text.build_text_packet_32x32(
            "HI",
            str(FONT),
            16,
            text.MODE_REPLACE,
            0,
            text.COLOR_RGB,
            (127, 0, 0),
            None,
            glyph_height=16,
        )[0][0]
    )
    header, metadata, glyphs = payload[:16], payload[16:30], payload[30:]

    assert (header[2], header[3]) == (3, 0)
    assert int.from_bytes(header[0:2], "little") == len(payload)
    assert int.from_bytes(header[9:13], "little") == zlib.crc32(payload[16:])

    assert int.from_bytes(metadata[0:2], "little") == 2  # char count
    assert metadata[2] == 1  # row-class flag
    assert (metadata[4], metadata[5], metadata[6]) == (text.MODE_REPLACE, 0, text.COLOR_RGB)
    assert metadata[7:10] == bytes([127, 0, 0])

    # Two glyph cells of 4 separator bytes + 16 packed bytes each.
    assert len(glyphs) == 2 * (4 + 16)
    for start in (0, 20):
        assert glyphs[start : start + 4] == b"\x02\xff\xff\xff"


def test_text_32x32_default_glyph_branch_still_uses_64_byte_cells_and_tag_5():
    payload = bytes(text.build_text_packet_32x32("HI", str(FONT))[0][0])
    glyphs = payload[30:]
    assert len(glyphs) == 2 * (4 + 64)
    for start in (0, 68):
        assert glyphs[start : start + 4] == b"\x05\xff\xff\xff"


def test_text_32x32_rejects_unknown_glyph_height():
    with pytest.raises(ValueError):
        text.build_text_packet_32x32("HI", str(FONT), glyph_height=24)


def test_text_32x32_char_count_is_len_text():
    payload = bytes(text.build_text_packet_32x32("HELLO", str(FONT))[0][0])
    metadata = payload[16:30]
    assert int.from_bytes(metadata[0:2], "little") == len("HELLO")


def test_gif_packets_match_golden():
    # Windows-only: Pillow's GIF encoder is not byte-stable across platform
    # wheels of the same release (CI 2026-07-20: all ubuntu jobs produced one
    # identical hash that differs from this Windows-made pin, so the variance
    # is per-platform-deterministic encoder output, not flakiness). The
    # cross-platform tripwires are the two tests below, which check what the
    # hash was really guarding: adaptation constraints and packet framing.
    if sys.platform != "win32":
        pytest.skip("GIF encoder hash pinned on Windows; not byte-stable cross-platform")
    data = gif.adapt_gif(str(GIF), 32, ResizeMode.FIT, True, (0, 0, 0), None)
    packets = gif.build_packets(data, gif.GIF_TYPE_NO_TIME_SIGNATURE, 1)
    flat = b"".join(bytes(p) for chunk in packets for p in chunk)
    assert hashlib.sha256(flat).hexdigest() == GIF_PACKETS_SHA256


def test_adapted_gif_decodes_within_device_limits():
    data = gif.adapt_gif(str(GIF), 32, ResizeMode.FIT, True, (0, 0, 0), None)
    with Image.open(io.BytesIO(data)) as img:
        assert img.format == "GIF"
        assert img.size == (32, 32)
        assert 1 <= getattr(img, "n_frames", 1) <= gif.MAX_FRAME_COUNT


def test_gif_build_packets_framing_golden_on_fixed_bytes():
    # Pinned on synthetic bytes so it holds on every platform: chunk framing
    # (headers, CRCs, BLE splitting) must not depend on which encoder build
    # produced the payload.
    data = bytes(range(256)) * 40  # 10240 bytes: multi-chunk
    packets = gif.build_packets(data, gif.GIF_TYPE_NO_TIME_SIGNATURE, 1)
    flat = b"".join(bytes(p) for chunk in packets for p in chunk)
    assert hashlib.sha256(flat).hexdigest() == ("3922650b8af50f963a9c4fbd72f2b8b31477ce27deaa4150ed31da74df2a0fcf")


def test_gif_time_sign_field_is_little_endian_five_for_the_default_key():
    """GOLDEN CORRECTION 2026-07-25 (vendor-app HCI capture, decoded with
    pyidotmatrix/btsnoop.py): the app's time-signature GIF header carries
    05 00 at header[13:15]. This builder wrote 00 0a for the default key=1 --
    wrong value AND wrong byte order (big-endian, unlike every other
    multi-byte field in the same header). The no-time-signature branch still
    writes 00 00, which is why the two hash goldens above are unaffected.
    """
    packets = gif.build_packets(b"\x01\x02\x03", gif.GIF_TYPE_DIY_ANIMATION, 1)
    header = bytes(packets[0][0])[:16]
    assert header[13:15] == b"\x05\x00"
    assert header[15] == gif.GIF_TYPE_DIY_ANIMATION
    # The rest of the header keeps its LE reading of the same bytes.
    assert int.from_bytes(header[13:15], "little") == 5


def test_gif_time_sign_keys_are_all_little_endian():
    for key, expected in ((1, 5), (2, 10), (3, 30), (4, 60), (5, 300), (99, 5)):
        packets = gif.build_packets(b"\x01\x02\x03", gif.GIF_TYPE_DIY_ANIMATION, key)
        header = bytes(packets[0][0])[:16]
        assert int.from_bytes(header[13:15], "little") == expected, key


def test_gif_no_time_signature_branch_unchanged():
    packets = gif.build_packets(b"\x01\x02\x03", gif.GIF_TYPE_NO_TIME_SIGNATURE, 1)
    assert bytes(packets[0][0])[13:15] == b"\x00\x00"


def test_gif_rejects_empty():
    with pytest.raises(ValueError):
        gif.build_packets(b"")


def test_adapt_gif_restores_loading_strategy_global(monkeypatch):
    # adapt_gif mutates Pillow's process-wide GifImagePlugin.LOADING_STRATEGY
    # to decode correctly, but must restore it afterward -- otherwise the
    # override leaks into every other GIF this process opens (item 6, code
    # review). Set a sentinel beforehand and confirm it's back after the call,
    # including when adapt_gif raises partway through.
    sentinel = GifImagePlugin.LoadingStrategy.RGB_ALWAYS
    monkeypatch.setattr(GifImagePlugin, "LOADING_STRATEGY", sentinel)

    gif.adapt_gif(str(GIF), 32, ResizeMode.FIT, True, (0, 0, 0), None)
    assert GifImagePlugin.LOADING_STRATEGY is sentinel

    with pytest.raises(FileNotFoundError):
        gif.adapt_gif("this-path-does-not-exist.gif", 32, ResizeMode.FIT, True, (0, 0, 0), None)
    assert GifImagePlugin.LOADING_STRATEGY is sentinel


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
