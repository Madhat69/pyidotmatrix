"""Golden + structural tests for text and GIF builders (Pillow-based).

Hashes were proven byte-identical to the lab implementation before pinning.
"""

import hashlib
import zlib
from pathlib import Path

from idotmatrix.imaging import ResizeMode
from idotmatrix.protocol import gif, text

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
