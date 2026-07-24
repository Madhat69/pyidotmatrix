"""Music-sync command builders. Pure functions.

The device has an onboard microphone, but the vendor app does NOT rely on it for
its music screen: the 2026-07-25 HCI capture (vendor-app btsnoop, decoded with
pyidotmatrix.btsnoop) shows the PHONE doing the FFT and streaming level bytes to
the panel at ~10 Hz -- see build_rhythm_levels, the real mechanism behind the
music screen. The older mode/rhythm-trigger commands below are kept as-is.
"""

from collections.abc import Sequence

from pyidotmatrix.validation import validate_byte, validate_percent

# Fixed prefix of a rhythm-levels frame. Byte 0 is 0x21 (33) even though the
# frame is 21 bytes long -- it is NOT a length field here, and "fixing" it to 21
# would stop matching the captured vendor traffic (2026-07-25 capture).
_RHYTHM_LEVELS_PREFIX = (0x21, 0x00, 0x01, 0x02, 0x00)

RHYTHM_LEVEL_COUNT = 16

# Highest level byte seen in the capture. Not a protocol limit -- the field is a
# full byte and the SDK accepts 0..255 -- but the vendor app never exceeded it.
OBSERVED_MAX_RHYTHM_LEVEL = 0x0D


def build_set_mic_type(mic_type: int, value: int = 100) -> bytearray:
    """Selects the microphone/sensitivity profile.

    Six bytes, not five: the frame's own length byte always said 6, but this
    builder emitted only 5 until the 2026-07-25 vendor-app HCI capture showed
    the trailing value byte on the wire -- observed [06 00 0b 80 01 64], i.e.
    mic_type=1 with value=100 (vendor-app HCI capture, pyidotmatrix/btsnoop.py).
    value is a 0..100 percent-style field; 100 is what the app sends.
    """
    validate_byte(mic_type, "mic_type")
    validate_percent(value, "value")
    return bytearray([6, 0, 0x0B, 0x80, mic_type, value])


def build_rhythm_levels(levels: Sequence[int]) -> bytearray:
    """Builds one frame of the music-screen level stream (16 band levels).

    Captured from the vendor app 2026-07-25 (HCI capture, decoded with
    pyidotmatrix/btsnoop.py): the app computes the spectrum host-side and pushes
    21-byte frames to the fa02 write characteristic at roughly 10 Hz. The stream
    is UNACKED -- the device sends no fa03 notification for these frames, so
    they must be written fire-and-forget (see IDotMatrixClient.music_sync.
    send_rhythm_levels).

    The app derives its 16 values from 8 FFT bands mirrored into a palindrome
    (b0..b7,b7..b0); nothing on the wire requires that shape, it just looks
    symmetric on the panel. Observed level bytes stayed within 0x00..0x0d
    (OBSERVED_MAX_RHYTHM_LEVEL); this builder accepts the full 0..255 byte range
    because the wire field is a byte and the ceiling is unprobed.

    UNTESTED ON OUR HARDWARE -- byte layout is capture-exact, but this SDK has
    never streamed it to a panel (see capabilities.py music_sync.rhythm_levels).
    """
    if len(levels) != RHYTHM_LEVEL_COUNT:
        raise ValueError(f"levels must be exactly {RHYTHM_LEVEL_COUNT} values, got {len(levels)}")
    for index, level in enumerate(levels):
        validate_byte(level, f"levels[{index}]")
    return bytearray([*_RHYTHM_LEVELS_PREFIX, *levels])


def build_send_image_rhythm(value: int) -> bytearray:
    """Shows a dancing figure that reacts as `value` changes.

    KNOWN_BROKEN on our panel (nothing rendered, 2026-07-21) and never sent by
    the vendor app in the 2026-07-25 capture -- build_rhythm_levels is the
    mechanism the app actually uses for its music screen.
    """
    validate_byte(value, "value")
    return bytearray([6, 0, 0, 2, value, 1])


def build_stop_rhythm() -> bytearray:
    return bytearray([6, 0, 0, 2, 0, 0])
