"""Animated GIF upload: adapt a GIF to the canvas, then build its packets.

Two stages, both ported verbatim from the research lab:
  adapt_gif   - fit/limit frames to what the device can handle (Pillow)
  build_packets - CRC + header + 4K chunk + BLE split (pure bytes)

The device has limited memory, so total frames and duration are capped.
"""

import binascii
import io
from os import PathLike

from PIL import GifImagePlugin, Image

from pyidotmatrix.imaging import ResizeMode, palettize, resize_to_canvas
from pyidotmatrix.protocol import bytes_

MAX_FRAME_COUNT = 64
DEFAULT_FRAME_DURATION_MS = 200
TOTAL_DURATION_LIMIT_MS = 2000

# Header prefixed to each 4K chunk (larger than the DIY header: adds CRC + timing).
_GIF_HEADER_SIZE = 16

# gif_type values that display an image; 12 = no time signature, 13 = DIY animation.
GIF_TYPE_NO_TIME_SIGNATURE = 12
GIF_TYPE_DIY_ANIMATION = 13


def adapt_gif(
    file_path: str | PathLike,
    canvas_size: int,
    resize_mode: ResizeMode = ResizeMode.FIT,
    do_palettize: bool = True,
    background_color: tuple[int, int, int] = (0, 0, 0),
    duration_per_frame_ms: int | None = None,
) -> bytes:
    """Loads a GIF, fits each frame to the canvas, caps the frame count, and
    re-encodes it to GIF bytes ready for build_packets."""
    GifImagePlugin.LOADING_STRATEGY = GifImagePlugin.LoadingStrategy.RGB_AFTER_DIFFERENT_PALETTE_ONLY

    with Image.open(file_path) as source:
        frames = []
        try:
            while True:
                frame = source.copy()
                if frame.size != (canvas_size, canvas_size):
                    frame = resize_to_canvas(
                        frame, canvas_size, resize_mode, Image.Resampling.NEAREST, background_color, mode="RGBA"
                    )
                if do_palettize:
                    frame = palettize(frame)
                frames.append(frame.copy())
                source.seek(source.tell() + 1)
        except EOFError:
            pass

        frames, frame_duration_ms = _limit_frames(source, frames, duration_per_frame_ms)

        buffer = io.BytesIO()
        frames[0].save(
            buffer,
            format="GIF",
            save_all=True,
            optimize=True,  # required: disabling it breaks the transfer
            append_images=frames[1:],
            loop=0,
            duration=frame_duration_ms,
            disposal=2,
        )
        return buffer.getvalue()


def build_packets(
    gif_data: bytes,
    gif_type: int = GIF_TYPE_NO_TIME_SIGNATURE,
    time_sign: int = 1,
    mtu_enabled: bool = True,
) -> list[list[bytearray]]:
    """Builds the BLE packets for adapted GIF bytes (see adapt_gif)."""
    if not gif_data:
        raise ValueError("gif_data cannot be empty")

    def header_builder(chunk: bytearray, payload: bytes, is_first: bool) -> bytes:
        return _build_header(chunk, payload, gif_type, time_sign, is_first)

    return bytes_.build_chunked_packets(gif_data, header_builder, mtu_enabled)


def _build_header(chunk: bytearray, payload: bytes, gif_type: int, time_sign: int, is_first: bool) -> bytes:
    """The 16-byte header prefixed to each 4K chunk."""
    header = bytearray(_GIF_HEADER_SIZE)
    header[0:2] = bytes_.short_to_bytes_le(len(chunk) + _GIF_HEADER_SIZE)  # length incl. header
    header[2] = 1  # command/type
    header[3] = 0  # sub-command
    header[4] = 0 if is_first else 2  # first vs continuation
    header[5:9] = bytes_.int_to_bytes_le(len(payload))  # total GIF size
    header[9:13] = bytes_.int_to_bytes_le(binascii.crc32(payload) & 0xFFFFFFFF)  # CRC32
    if gif_type == GIF_TYPE_NO_TIME_SIGNATURE:
        header[13:15] = b"\x00\x00"
    else:
        header[13:15] = _convert_time_sign(time_sign).to_bytes(2, "big")
    header[15] = gif_type & 0xFF
    return bytes(header)


def _convert_time_sign(key: int) -> int:
    """Maps the app's time-sign key to the device's expected value."""
    return {1: 10, 2: 30, 3: 60, 4: 300}.get(key, 5)


def _limit_frames(
    source: Image.Image, frames: list, duration_ms: int | None
) -> tuple[list, float]:
    """Caps frame count and total duration to what the device can handle."""
    # A caller-supplied duration is used as-is; otherwise derive one (which may
    # be fractional -- see _frame_duration), hence the float-typed local.
    duration: float = _frame_duration(source, len(frames)) if duration_ms is None else duration_ms

    if len(frames) <= 1:
        return frames, duration  # nothing to sample

    # Hard cap: the device cannot handle more than MAX_FRAME_COUNT frames,
    # regardless of duration.
    if len(frames) > MAX_FRAME_COUNT:
        frames = _sample_frames(frames, MAX_FRAME_COUNT - 2)  # -2: first/last always kept

    # Duration cap: drop intermediate frames so uploads stay fast.
    if len(frames) * duration > TOTAL_DURATION_LIMIT_MS:
        keep = min(MAX_FRAME_COUNT - 2, int(TOTAL_DURATION_LIMIT_MS / duration) - 2)
        if keep < len(frames):
            frames = _sample_frames(frames, keep)
    return frames, duration


def _frame_duration(source: Image.Image, frame_count: int) -> float:
    """Chooses a per-frame duration from the GIF, or computes a sane one."""
    duration = source.info.get("duration", DEFAULT_FRAME_DURATION_MS)
    if not isinstance(duration, int) or duration <= 0:
        if frame_count > MAX_FRAME_COUNT:
            duration = TOTAL_DURATION_LIMIT_MS / MAX_FRAME_COUNT
        else:
            duration = TOTAL_DURATION_LIMIT_MS / frame_count
    return max(16, duration)  # at least 16ms (~60fps)


def _sample_frames(frames: list, keep: int) -> list:
    """Evenly samples `keep` intermediate frames, always keeping first and last."""
    result = [frames[0], frames[-1]]
    if keep <= 0:
        return result
    middle = frames[1:-1]
    step = len(middle) // keep
    for i in range(0, len(middle), step):
        if len(result) < MAX_FRAME_COUNT - 1:
            result.insert(-1, middle[i])
    return result
