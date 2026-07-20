"""Hardware probe: screen-on-duration / auto-dim timer.

Confirms two things that can't be learned from the decompile alone:
  1. Whether build_read_screen_timeout() actually gets a reply on fa03.
  2. What unit the value byte represents (seconds? minutes? a preset enum?).

Usage:
    python probes/probe_screen_timeout.py [--mac AA:BB:CC:DD:EE:FF] [--value 5]

Not run in CI -- no hardware access exists in the dev environment this was
written in. A human runs this with a real panel in view and records what they
observe at each VISUAL CHECK line.
"""

import argparse
import asyncio

from pyidotmatrix.client import IDotMatrixClient
from pyidotmatrix.protocol import common
from pyidotmatrix.screen import ScreenSize


def _print_ack(ack) -> None:
    print(
        f"[listener] ack: type={ack.command_type} subtype={ack.command_subtype} "
        f"accepted={ack.accepted} raw={ack.raw.hex()}"
    )


async def main(mac: str | None, value: int) -> None:
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, mac_address=mac)
    client.add_response_listener(_print_ack)

    print("connecting...")
    await client.connect()
    try:
        print("\n--- read_screen_timeout ---")
        ack = await client.await_device_ack(common.build_read_screen_timeout())
        if ack is None:
            print(
                "VISUAL CHECK: no fa03 reply arrived within the timeout. Record: "
                "the read variant appears to not respond on this firmware."
            )
        else:
            print(
                f"VISUAL CHECK: raw fa03 reply = {ack.raw.hex()} (accepted={ack.accepted}). "
                "Record whether this looks like the standard 5-byte accept/reject ack, or "
                "whether a longer/different frame carries the current value -- if so, note "
                "its exact bytes here for protocol/response.py to learn later."
            )

        print(f"\n--- set_screen_timeout({value}) ---")
        await client.common.set_screen_timeout(value)
        print(
            f"VISUAL CHECK: watch the panel. Does it dim or turn off after approximately "
            f"{value} seconds? {value} minutes? Something else entirely? Time it with a "
            f"stopwatch and note the actual elapsed duration observed."
        )
        input("Press Enter once you've observed the timeout behavior...")
    finally:
        await client.disconnect()
        print("disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", default=None, help="device MAC address; omit to auto-discover")
    parser.add_argument("--value", type=int, default=5, help="screen timeout value to set (0..254)")
    args = parser.parse_args()
    asyncio.run(main(args.mac, args.value))
