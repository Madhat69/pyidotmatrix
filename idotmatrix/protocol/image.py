"""DIY image-mode packet builders.

A full RGB frame is uploaded in "DIY" mode. The frame bytes are chunked to 4096
bytes, each chunk gets a 9-byte header (length, continuation flag, total size),
and each header+chunk is split into BLE packets. Pure functions, no I/O.
"""

from idotmatrix.protocol import bytes_

# DIY mode values for the set-mode command (byte 4 of the payload).
DIY_MODE_ENABLE = 1
DIY_MODE_DISABLE = 0

_DIY_HEADER_SIZE = 9


def build_set_diy_mode(enable: bool = True) -> bytearray:
    """Command that enters or leaves DIY draw mode. Send before the first frame."""
    mode = DIY_MODE_ENABLE if enable else DIY_MODE_DISABLE
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
