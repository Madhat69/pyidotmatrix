"""Effect-mode command builders. Pure functions.

The device animates one of seven built-in effects using 2..7 colors.

Wire format (CONFIRMED-FROM-SOURCE: docs/reverse-engineering/APK_SECOND_PASS.md
Q5(a), `MutilColorAgreement.sendMutilColor()`, MutilColorAgreement.java:42-72):

    [len, 0, 3, 2, style, speed, colorCount] + colorCount * 3 RGB bytes

Byte 5 is a real speed field in the vendor app (`bArr[5] = (byte)
lightsColor.getSpeed()`), distinct from saturation. The lab-era port hardcoded
it to 90; build_show now exposes it, defaulting to the historical 90 so
existing callers keep sending byte-identical commands.

Deliberately NOT implemented, with why:
  * Saturation: the app passes every RGB channel through
    `ColorConverter.calculationByColour(component, saturation)` before it hits
    the wire (APK_SECOND_PASS.md Q5(a)); the RE docs record that the function
    exists but not its formula, so this builder takes final RGB values and
    leaves any saturation adjustment to the caller.
  * Color counts beyond 7: colorCount is a single wire byte, but neither the
    app-side maximum nor how byte 0 (`len`, our lab-derived `6 + colorCount`)
    behaves for larger lists is documented (FEATURE_MATRIX.md "Multi-color
    effect" row flags this as an open comparison), so the 2..7 lab range
    stands.
"""

from pyidotmatrix.validation import validate_rgb

MIN_COLORS = 2
MAX_COLORS = 7

# Historical hardcoded speed byte; effect mode with this value was activated on
# real 32x32 hardware (persistence probes 2026-07-17, ROADMAP.md section 3).
SPEED_DEFAULT = 90

# Per-chunk payload sizes of the bespoke effect re-packetization scheme
# (APK_SECOND_PASS.md Q5(a), `MutilColorAgreement.getSendData()`, :84-119):
# 96 bytes when the app negotiated a device MTU, else 18.
CHUNK_PAYLOAD_WITH_MTU = 96
CHUNK_PAYLOAD_WITHOUT_MTU = 18


def build_show(
    style: int,
    colors: list[tuple[int, int, int]],
    speed: int = SPEED_DEFAULT,
) -> bytearray:
    """Builds the flat effect command.

    speed: byte offset 5 (APK_SECOND_PASS.md Q5(a)). The decompile shows only a
    byte cast, so any 0..255 value is accepted here; the app-side legal range
    is undocumented. ⚠ SOURCE-DERIVED for speed != 90, unverified on hardware
    (only the historical 90 has ever been sent by this SDK).
    """
    if style not in range(7):
        raise ValueError(f"effect style must be 0..6, got {style}")
    if not (MIN_COLORS <= len(colors) <= MAX_COLORS):
        raise ValueError(f"effect needs {MIN_COLORS}..{MAX_COLORS} colors, got {len(colors)}")
    if speed not in range(256):
        raise ValueError(f"effect speed must be 0..255, got {speed}")
    for color in colors:
        validate_rgb(color)

    # The two length fields count colors, not color components.
    components = [channel for color in colors for channel in color]
    return bytearray(
        [
            6 + len(colors),
            0, 3, 2,
            style % 256,
            speed,
            len(colors) % 256,
        ]
        + components
    )


def build_show_packets(
    style: int,
    colors: list[tuple[int, int, int]],
    speed: int = SPEED_DEFAULT,
    mtu_negotiated: bool = True,
) -> list[bytearray]:
    """Builds the effect command in the vendor app's own transmission framing.

    ⚠ SOURCE-DERIVED, unverified on hardware. The app never sends the flat
    command directly: `MutilColorAgreement.getSendData()` (:84-119, per
    docs/reverse-engineering/APK_SECOND_PASS.md Q5(a)) re-packetizes it into
    chunks of at most 96 payload bytes (MTU negotiated) or 18 (not negotiated),
    each prefixed with a 2-byte `[chunkLen + 1, chunkIndex]` sub-header. This
    is a bespoke scheme, distinct from the 4096/509-byte chunking that
    Timer/Schedule/GIF/Image use. Whether the sub-header counts toward the
    96/18 budget is not recorded in the RE doc; this port treats the budget as
    payload-only.

    Our flat build_show output has worked on 32x32 hardware for <= 7 colors,
    so this framing is optional there; it exists to match the app's observed
    wire behavior for firmware that may require it.
    """
    flat = build_show(style, colors, speed)
    chunk_payload = CHUNK_PAYLOAD_WITH_MTU if mtu_negotiated else CHUNK_PAYLOAD_WITHOUT_MTU

    packets: list[bytearray] = []
    for index, start in enumerate(range(0, len(flat), chunk_payload)):
        chunk = flat[start:start + chunk_payload]
        packets.append(bytearray([len(chunk) + 1, index]) + chunk)
    return packets
