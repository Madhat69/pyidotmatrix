"""Hardware probe: what does the graffiti 'mirror' byte actually do?

protocol/graffiti.py treats header byte 3 as "mirror 1-4" (a guess from the
original research lab, never verified). The APK's DiyImageMoveType enum, used by
a related-but-distinct command, suggests a 5-way option set instead:

    0 = NO_EFFECT
    1 = HORIZONTAL_MIRROR
    2 = VERTICAL_MIRROR
    3 = OVERALL_MOVEMENT
    4 = ERASE

This probe draws a small asymmetric pattern, then sends the *same* graffiti
set-pixels command with byte 3 = 0, 1, 2, 3, 4 in turn, pausing between each so
a human can watch what changes on the panel.

The shipped graffiti.build_set_pixels() validates mirror to 1..4 (hardware-proven
range) and we do not relax that validation here -- the mirror=0 payload is built
locally in this probe instead, exactly matching the shipped wire format.

Usage:
    python probes/probe_graffiti_mirror.py [--mac AA:BB:CC:DD:EE:FF]

Not run in CI -- no hardware access exists in the dev environment this was
written in. A human runs this with a real panel in view and records what they
observe at each VISUAL CHECK line.
"""

import argparse
import asyncio

from idotmatrix.client import IDotMatrixClient
from idotmatrix.protocol import graffiti
from idotmatrix.screen import ScreenSize

_HYPOTHESIS_LABELS = {
    0: "NO_EFFECT",
    1: "HORIZONTAL_MIRROR",
    2: "VERTICAL_MIRROR",
    3: "OVERALL_MOVEMENT",
    4: "ERASE",
}

# An asymmetric "L" shape: distinguishable from its own mirror/rotation, so a
# mirror/move effect is obvious at a glance.
_TEST_PATTERN = [(0, 0), (0, 1), (0, 2), (1, 0), (2, 0)]
_TEST_COLOR = (0, 255, 0)


def _build_raw_pixels_payload(color: tuple[int, int, int], xys: list[tuple[int, int]], mirror: int) -> bytearray:
    """Local reimplementation of graffiti.build_set_pixels's wire format.

    Exists only to construct the mirror=0 payload the shipped builder's
    validation intentionally rejects (mirror 1..4 is the hardware-proven range;
    0 is an untested hypothesis from DiyImageMoveType, worth probing but not
    worth relaxing the shipped range check for). Keep this in sync with
    protocol/graffiti.py's header layout if that ever changes.
    """
    header_size = 8
    red, green, blue = color
    size = header_size + 2 * len(xys)
    payload = bytearray(
        [size % 256, size // 256, 5, mirror, 0, red, green, blue] + [0] * (size - header_size)
    )
    for i, (x, y) in enumerate(xys):
        payload[header_size + 2 * i] = x
        payload[header_size + 2 * i + 1] = y
    return payload


async def main(mac: str | None) -> None:
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, mac_address=mac)
    client.add_response_listener(
        lambda ack: print(
            f"[listener] ack: type={ack.command_type} subtype={ack.command_subtype} "
            f"accepted={ack.accepted} raw={ack.raw.hex()}"
        )
    )
    # Note: graffiti commands produce no device ack (see BleTransport.await_device_ack),
    # so this probe relies entirely on visual observation, not acks, for each mirror value.

    print("connecting...")
    await client.connect()
    try:
        print("clearing the screen and drawing the base 'L' pattern with mirror=1 (no effect)...")
        await client.display.show_frame(bytes(client.screen_size.pixel_count * 3))
        await client.graffiti.set_pixels(_TEST_COLOR, _TEST_PATTERN, mirror=graffiti.MIRROR_NONE)
        print(
            "VISUAL CHECK: confirm you see a small green 'L' shape near the top-left corner "
            "(a vertical stroke down from the corner, plus a horizontal stroke right from the corner)."
        )
        input("Press Enter to begin testing mirror values...")

        for mirror in (0, 1, 2, 3, 4):
            label = _HYPOTHESIS_LABELS[mirror]
            print(f"\n--- mirror={mirror}  (hypothesis: {label}) ---")
            if mirror == 0:
                payload = _build_raw_pixels_payload(_TEST_COLOR, _TEST_PATTERN, mirror)
                # GraffitiFeature._send is the same transport write the shipped builder
                # uses; only the payload construction bypasses the shipped validation.
                await client.graffiti._send(payload)
            else:
                await client.graffiti.set_pixels(_TEST_COLOR, _TEST_PATTERN, mirror=mirror)
            print(
                f"VISUAL CHECK: with mirror={mirror} sent, does the pattern match the "
                f"'{label}' hypothesis? Describe what actually changed on the panel "
                f"(nothing / mirrored horizontally / mirrored vertically / moved / erased / other)."
            )
            input("Press Enter to test the next mirror value...")
    finally:
        await client.disconnect()
        print("disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", default=None, help="device MAC address; omit to auto-discover")
    args = parser.parse_args()
    asyncio.run(main(args.mac))
