"""DIY image-mode packet builders.

A full RGB frame is uploaded in "DIY" mode. The frame bytes are chunked to 4096
bytes, each chunk gets a 9-byte header (length, continuation flag, total size),
and each header+chunk is split into BLE packets. Pure functions, no I/O.
"""

from typing import Optional

from idotmatrix.protocol import bytes_

# DIY mode values for the set-mode command (byte 4 of the payload), named after
# the APK's `DiyImageFun` enum. Modes 2/3 are accepted by the device but their
# display behavior is untested on GlanceOS hardware — see ROADMAP.
QUIT_NOSAVE_KEEP_PREV = 0
ENTER_CLEAR_CUR_SHOW = 1
QUIT_STILL_CUR_SHOW = 2
ENTER_NO_CLEAR_CUR_SHOW = 3

_DIY_MODES = (QUIT_NOSAVE_KEEP_PREV, ENTER_CLEAR_CUR_SHOW, QUIT_STILL_CUR_SHOW, ENTER_NO_CLEAR_CUR_SHOW)

# Backward-compatible aliases for the two modes this driver originally named.
DIY_MODE_ENABLE = ENTER_CLEAR_CUR_SHOW
DIY_MODE_DISABLE = QUIT_NOSAVE_KEEP_PREV

_DIY_HEADER_SIZE = 9


def build_set_diy_mode(enable: bool = True, mode: Optional[int] = None) -> bytearray:
    """Command that enters or leaves DIY draw mode. Send before the first frame.

    `enable` selects between the two originally-supported modes (ENTER_CLEAR_CUR_SHOW
    / QUIT_NOSAVE_KEEP_PREV). Pass `mode` explicitly to use one of the full four
    DiyImageFun values instead — QUIT_STILL_CUR_SHOW and ENTER_NO_CLEAR_CUR_SHOW are
    accepted by the device but their on-screen effect is unverified; `mode` overrides
    `enable` when given.
    """
    if mode is None:
        mode = ENTER_CLEAR_CUR_SHOW if enable else QUIT_NOSAVE_KEEP_PREV
    elif mode not in _DIY_MODES:
        raise ValueError(f"diy mode must be one of {_DIY_MODES} (DiyImageFun), got {mode}")
    return bytearray([5, 0, 4, 1, mode])


def build_frame_packets(rgb: bytes) -> list[list[bytearray]]:
    """Builds the BLE packets for one full RGB frame.

    Returns a list of chunks, each a list of BLE packets. The transport sends
    every packet in order; only the final packet of the final chunk is acked.
    """
    chunks = bytes_.chunk_by_size(rgb, bytes_.CHUNK_SIZE_4096)
    return [
        bytes_.split_into_ble_packets(_build_header(chunk, len(rgb), is_first=index == 0) + chunk)
        for index, chunk in enumerate(chunks)
    ]


def _build_header(chunk: bytearray | bytes, total_length: int, is_first: bool) -> bytes:
    """The 9-byte header prefixed to each 4K chunk."""
    header = bytearray(_DIY_HEADER_SIZE)
    header[0:2] = bytes_.short_to_bytes_le(len(chunk) + _DIY_HEADER_SIZE)  # length incl. header
    header[2] = 0  # command/type
    header[3] = 0  # sub-command/subtype
    header[4] = 0 if is_first else 2  # 0 = first packet, 2 = continuation
    header[5:9] = bytes_.int_to_bytes_le(total_length)  # total frame size
    return bytes(header)
