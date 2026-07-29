"""Effect-mode command builders. Pure functions.

The device animates one of seven built-in effects using 2..7 colors.

Wire format (CONFIRMED-FROM-SOURCE: docs/reverse-engineering/APK_SECOND_PASS.md
Q5(a), `MutilColorAgreement.sendMutilColor()`, MutilColorAgreement.java:42-72):

    [len_lsb, len_msb, 3, 2, style, speed, colorCount] + colorCount * 3 RGB bytes

Bytes 0-1 are the TOTAL frame length, little-endian: the vendor app's 7-color
command opens `1c 00` = 28 = 7 header bytes + 21 color bytes (2026-07-25
vendor-app HCI capture, docs/PROBE_PLAN.md P1). The lab-era port wrote
`6 + colorCount` there -- 13 for the same frame -- which is the leading
explanation for why every one of our speed probes saw byte 5 behave as if it
were inert while the app's dial worked (probes/probe_p1_followups.py group A,
2026-07-25: the app-exact frame DOES change the animation rate).

Byte 5 is a real speed field in the vendor app (`bArr[5] = (byte)
lightsColor.getSpeed()`), distinct from saturation. The lab-era port hardcoded
it to 90; build_show exposes it, defaulting to the historical 90.

Deliberately NOT implemented, with why:
  * Saturation: the app passes every RGB channel through
    `ColorConverter.calculationByColour(component, saturation)` before it hits
    the wire (APK_SECOND_PASS.md Q5(a)); the RE docs record that the function
    exists but not its formula, so this builder takes final RGB values and
    leaves any saturation adjustment to the caller.
  * Color counts beyond 7: colorCount is a single wire byte, and the app-side
    maximum is undocumented (FEATURE_MATRIX.md "Multi-color effect" row flags
    this as an open comparison), so the 2..7 lab range stands. The length field
    itself no longer caps us -- it is a 16-bit little-endian total, so it
    spans any list the count byte could describe.
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
    is undocumented. Hardware-verified 2026-07-25 at 5 and 100 on the reference
    32x32 (probes/probe_p1_followups.py A1-A3): visibly slow vs smooth.
    """
    if style not in range(7):
        raise ValueError(f"effect style must be 0..6, got {style}")
    if not (MIN_COLORS <= len(colors) <= MAX_COLORS):
        raise ValueError(f"effect needs {MIN_COLORS}..{MAX_COLORS} colors, got {len(colors)}")
    if speed not in range(256):
        raise ValueError(f"effect speed must be 0..255, got {speed}")
    for color in colors:
        validate_rgb(color)

    # Bytes 0-1 are the total frame length (7 header + 3 per color), matching
    # the captured app frame `1c 00 03 02 00 SPEED 07` for 7 colors; byte 6 is
    # the color COUNT. The MSB is 0 for every count the count byte can express,
    # but it is computed rather than pinned so the field stays honest.
    components = [channel for color in colors for channel in color]
    size = 7 + len(components)
    return bytearray(
        [
            size % 256,  # length LSB
            size // 256,  # length MSB (0 across the whole legal range)
            3,
            2,
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

    Length bytes here, after the 2026-07-25 audit: this builder carried the
    same malformed length byte build_show did, inside the flat command it
    slices -- fixed transitively by that fix, so the payload the device
    reassembles is now the app-exact frame. The 2-byte sub-header's own
    `chunkLen + 1` is a different count (chunk payload plus the index byte,
    excluding the length byte itself) and is CONFIRMED-FROM-SOURCE, so it is
    left as the decompile states it. show_chunked's inert hardware result may
    therefore have been the embedded length byte rather than the framing --
    untested, so capabilities.py keeps it KNOWN_BROKEN.
    """
    flat = build_show(style, colors, speed)
    chunk_payload = CHUNK_PAYLOAD_WITH_MTU if mtu_negotiated else CHUNK_PAYLOAD_WITHOUT_MTU

    packets: list[bytearray] = []
    for index, start in enumerate(range(0, len(flat), chunk_payload)):
        chunk = flat[start : start + chunk_payload]
        packets.append(bytearray([len(chunk) + 1, index]) + chunk)
    return packets
