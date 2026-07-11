"""Hardware probe: DiyImageFun modes 2 and 3.

Our image.py only ever used modes 0/1 (QUIT_NOSAVE_KEEP_PREV / ENTER_CLEAR_CUR_SHOW).
The device accepts 2/3 too (QUIT_STILL_CUR_SHOW / ENTER_NO_CLEAR_CUR_SHOW) but their
on-screen effect has never been observed. Two hypotheses worth confirming:

  - ENTER_NO_CLEAR_CUR_SHOW (3): entering DIY mode *without* the black-flash that
    _ensure_diy_mode() currently causes on the first frame after connect.
  - QUIT_STILL_CUR_SHOW (2): leaving DIY mode while keeping the last frame visible,
    instead of the panel going blank.

Usage:
    python probes/probe_diy_modes.py [--mac AA:BB:CC:DD:EE:FF]

Not run in CI -- no hardware access exists in the dev environment this was
written in. A human runs this with a real panel in view and records what they
observe at each VISUAL CHECK line.
"""

import argparse
import asyncio

from idotmatrix.client import IDotMatrixClient
from idotmatrix.protocol import image
from idotmatrix.screen import ScreenSize


def _print_ack(ack) -> None:
    print(
        f"[listener] ack: type={ack.command_type} subtype={ack.command_subtype} "
        f"accepted={ack.accepted} raw={ack.raw.hex()}"
    )


def _build_test_frame(width: int, height: int) -> bytes:
    """A red-left / blue-right split -- easy to recognize at a glance so any
    flash or persistence during mode transitions is obvious."""
    pixels = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            offset = (y * width + x) * 3
            color = (255, 0, 0) if x < width // 2 else (0, 0, 255)
            pixels[offset:offset + 3] = bytes(color)
    return bytes(pixels)


async def main(mac: str | None) -> None:
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, mac_address=mac)
    client.add_response_listener(_print_ack)

    print("connecting...")
    await client.connect()
    try:
        frame = _build_test_frame(client.screen_size.width, client.screen_size.height)

        print("\n--- baseline: normal show_frame (ENTER_CLEAR_CUR_SHOW path) ---")
        await client.display.show_frame(frame)
        print(
            "VISUAL CHECK: confirm the panel shows red on the left half, blue on the "
            "right half. Note whether you saw a black flash before it appeared -- this "
            "is the baseline _ensure_diy_mode() behavior we're comparing against."
        )
        input("Press Enter to continue...")

        print("\n--- ENTER_NO_CLEAR_CUR_SHOW (mode 3) ---")
        ack = await client.await_device_ack(image.build_set_diy_mode(mode=image.ENTER_NO_CLEAR_CUR_SHOW))
        print(f"ack for mode 3: {ack}")
        print(
            "VISUAL CHECK: did entering DIY mode this way cause a black flash, or did "
            "the red/blue frame stay visible without interruption?"
        )
        input("Press Enter to continue...")

        print("re-uploading the test frame under mode 3 DIY state...")
        # Reaching into the client's private transport: client.display.show_frame() would
        # re-enter DIY mode via _ensure_diy_mode(), undoing the mode-3 state we just set.
        # This probe needs the raw frame-packet write without that side effect.
        await client._transport.write_packets(image.build_frame_packets(frame), response=True)
        print("VISUAL CHECK: confirm the red/blue frame is (still) showing correctly.")
        input("Press Enter to continue...")

        print("\n--- QUIT_STILL_CUR_SHOW (mode 2) ---")
        ack = await client.await_device_ack(image.build_set_diy_mode(mode=image.QUIT_STILL_CUR_SHOW))
        print(f"ack for mode 2: {ack}")
        print(
            "VISUAL CHECK: after quitting DIY mode this way, does the last frame remain "
            "displayed, or does the panel go blank / revert to some default screen?"
        )
        input("Press Enter to finish...")
    finally:
        await client.disconnect()
        print("disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", default=None, help="device MAC address; omit to auto-discover")
    args = parser.parse_args()
    asyncio.run(main(args.mac))
