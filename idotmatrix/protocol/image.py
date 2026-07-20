"""DIY image-mode packet builders.

A full RGB frame is uploaded in "DIY" mode. The frame bytes are chunked to 4096
bytes, each chunk gets a 9-byte header (length, continuation flag, total size),
and each header+chunk is split into BLE packets. Pure functions, no I/O.
"""

from typing import Optional

from idotmatrix.protocol import bytes_

# DIY mode values for the set-mode command (byte 4 of the payload), named after
# the APK's `DiyImageFun` enum. HARDWARE-CONFIRMED 2026-07-12 on a real 32x32
# panel: ENTER_NO_CLEAR_CUR_SHOW (3) enters DIY mode with NO black flash (unlike
# ENTER_CLEAR_CUR_SHOW, which flashes black), and frame uploads sent while in
# mode-3 state render correctly; QUIT_STILL_CUR_SHOW (2) quits DIY mode while
# keeping the last frame visible on screen.
#
# HARDWARE-CONFIRMED 2026-07-17 (A/B, Architect ruling O-27, DAEMON_PLAN.md):
# mode 3 does NOT reliably take over an EFFECT state -- the panel silently
# keeps running the effect (deltas paint through, full frames are swallowed)
# -- and the device still acks accepted=True regardless (an ack confirms the
# write was received, not that DIY mode actually took). Mode 1 always takes,
# at the cost of a black flash. See BleDisplay._ensure_diy_mode /
# BleDisplay.set_entry_clear, which the daemon (not this driver) uses to pick
# mode 1 vs. mode 3 per O-27's entry policy -- this module stays opinion-free
# about when each is safe.
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
    DiyImageFun values instead — HARDWARE-CONFIRMED 2026-07-12: QUIT_STILL_CUR_SHOW
    (2) quits keeping the last frame visible, ENTER_NO_CLEAR_CUR_SHOW (3) enters
    with no black flash; `mode` overrides `enable` when given.

    CAVEAT (HARDWARE-CONFIRMED 2026-07-17, O-27): mode 3 does not reliably take
    over an EFFECT state -- the panel silently keeps running the effect, and the
    device still acks accepted=True anyway (an ack confirms receipt, not that
    DIY mode actually took). Mode 1 always takes, at the cost of a black flash.
    Choosing between them per connection is policy, not this builder's concern
    -- see BleDisplay.set_entry_clear.
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
    return bytes_.build_chunked_packets(rgb, _build_header)


def _build_header(chunk: bytearray, payload: bytes, is_first: bool) -> bytes:
    """The 9-byte header prefixed to each 4K chunk."""
    header = bytearray(_DIY_HEADER_SIZE)
    header[0:2] = bytes_.short_to_bytes_le(len(chunk) + _DIY_HEADER_SIZE)  # length incl. header
    header[2] = 0  # command/type
    header[3] = 0  # sub-command/subtype
    header[4] = 0 if is_first else 2  # 0 = first packet, 2 = continuation
    header[5:9] = bytes_.int_to_bytes_le(len(payload))  # total frame size
    return bytes(header)
