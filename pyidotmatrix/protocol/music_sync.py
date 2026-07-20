"""Music-sync command builders. Pure functions.

Not referenced by the iDotMatrix app; kept for feature parity. The device has an
onboard microphone, so streaming host audio is out of scope — only the mode and
rhythm-trigger commands are provided.
"""

from pyidotmatrix.validation import validate_byte


def build_set_mic_type(mic_type: int) -> bytearray:
    validate_byte(mic_type, "mic_type")
    return bytearray([6, 0, 11, 128, mic_type])


def build_send_image_rhythm(value: int) -> bytearray:
    """Shows a dancing figure that reacts as `value` changes."""
    validate_byte(value, "value")
    return bytearray([6, 0, 0, 2, value, 1])


def build_stop_rhythm() -> bytearray:
    return bytearray([6, 0, 0, 2, 0, 0])
