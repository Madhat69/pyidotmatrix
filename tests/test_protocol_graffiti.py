"""Golden + structural tests for graffiti (set-pixels) packet building."""

import pytest

from idotmatrix.protocol import graffiti


def test_single_pixel_matches_golden():
    # Pinned from the verified-equivalent build.
    payload = graffiti.build_set_pixels((10, 20, 30), [(1, 2)])
    assert bytes(payload).hex() == "0a000501000a141e0102"


def test_header_and_length():
    payload = graffiti.build_set_pixels((255, 0, 0), [(3, 4), (5, 6)])
    size = 8 + 2 * 2
    assert payload[0] == size % 256
    assert payload[1] == size // 256
    assert payload[2] == 5  # graffiti mode
    assert payload[5:8] == bytearray([255, 0, 0])  # color
    assert payload[8:12] == bytearray([3, 4, 5, 6])  # coordinates


def test_length_spans_two_bytes_past_255():
    payload = graffiti.build_set_pixels((0, 0, 0), [(0, 0)] * 200)
    size = 8 + 2 * 200  # 408
    assert payload[0] == size % 256
    assert payload[1] == size // 256  # 1


def test_rejects_too_many_pixels():
    with pytest.raises(ValueError):
        graffiti.build_set_pixels((0, 0, 0), [(0, 0)] * (graffiti.MAX_PIXELS_PER_COMMAND + 1))


def test_mirror_defaults_to_none():
    assert graffiti.build_set_pixels((1, 2, 3), [(0, 0)])[3] == graffiti.MIRROR_NONE


def test_mirror_sets_byte_three():
    assert graffiti.build_set_pixels((1, 2, 3), [(0, 0)], mirror=3)[3] == 3


@pytest.mark.parametrize("mirror", [0, 5, -1])
def test_mirror_out_of_range_rejected(mirror):
    with pytest.raises(ValueError):
        graffiti.build_set_pixels((0, 0, 0), [(0, 0)], mirror=mirror)
