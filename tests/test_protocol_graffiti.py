"""Golden + structural tests for graffiti (set-pixels) packet building."""

import pytest

from pyidotmatrix.protocol import graffiti


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


def test_byte3_is_pinned_to_the_only_drawing_value():
    # HARDWARE-MAPPED 2026-07-21: byte 3 = 1 is the sole value the device
    # draws for (2 nacks, 0/3/4 silently swallowed); it is not caller-visible.
    payload = graffiti.build_set_pixels((1, 2, 3), [(0, 0)])
    assert payload[3] == 1


def test_move_type_defaults_to_none_and_sets_byte_four():
    assert graffiti.build_set_pixels((1, 2, 3), [(0, 0)])[4] == graffiti.MOVE_NONE
    payload = graffiti.build_set_pixels(
        (1, 2, 3), [(0, 0)], move_type=graffiti.MOVE_VERTICAL_MIRROR
    )
    assert payload[4] == graffiti.MOVE_VERTICAL_MIRROR
    assert payload[3] == 1  # byte 3 stays pinned regardless


@pytest.mark.parametrize("move_type", [3, 4, 5, -1])
def test_unmapped_move_types_rejected(move_type):
    # 3 (OVERALL_MOVEMENT) and 4 (ERASE) exist in the APK enum but drew plainly
    # or unresolved on hardware -- not exposed until their semantics are mapped.
    with pytest.raises(ValueError):
        graffiti.build_set_pixels((0, 0, 0), [(0, 0)], move_type=move_type)
