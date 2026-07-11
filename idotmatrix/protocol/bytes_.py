"""Byte-level helpers shared by the packet builders.

Large payloads (image frames) are sent as 4096-byte chunks, each prefixed with a
small header, and every chunk is then split into BLE-sized packets by the MTU.
These are the pieces common to that layering. Pure functions, no I/O.
"""

# BLE packet sizes from the decompiled iDotMatrix app (GifAgreement.java).
MTU_SIZE_IF_ENABLED = 509
MTU_SIZE_IF_DISABLED = 18

# Outer chunk size for large payloads, defined by the device protocol.
CHUNK_SIZE_4096 = 4096


def int_to_bytes_le(value: int, length: int = 4) -> bytearray:
    """Little-endian bytearray of the given length."""
    return bytearray(value.to_bytes(length, byteorder="little"))


def short_to_bytes_le(value: int) -> bytearray:
    """Little-endian 2-byte bytearray."""
    return bytearray(value.to_bytes(2, byteorder="little"))


def chunk_by_size(data: bytearray | bytes, chunk_size: int) -> list[bytearray]:
    """Splits data into consecutive chunks of at most chunk_size bytes."""
    return [bytearray(data[i:i + chunk_size]) for i in range(0, len(data), chunk_size)]


def split_into_ble_packets(data: bytearray | bytes, mtu_enabled: bool = True) -> list[bytearray]:
    """Splits one large chunk (header + data) into BLE-transmission-sized packets."""
    mtu = MTU_SIZE_IF_ENABLED if mtu_enabled else MTU_SIZE_IF_DISABLED
    return chunk_by_size(data, mtu)
