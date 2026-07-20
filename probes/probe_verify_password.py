"""Hardware probe: verify_password ack shape.

build_verify_password's bytes are confirmed from the APK, but the shape of the
device's reply was never observed (see docs/APK_PROTOCOL_FINDINGS.md, finding #1).
This probe sends it and prints the raw fa03 ack bytes so that shape can be
recorded -- ideally run twice: once with a password that matches one already set
via client.common.set_password(), and once with a wrong one, to see whether
accepted flips between the two.

Usage:
    python probes/probe_verify_password.py 123456 [--mac AA:BB:CC:DD:EE:FF]

Not run in CI -- no hardware access exists in the dev environment this was
written in. A human runs this with a real, already password-protected device and
records what they observe at each VISUAL CHECK line.
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


async def main(mac: str | None, password: int) -> None:
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, mac_address=mac)
    client.add_response_listener(_print_ack)

    print("connecting...")
    await client.connect()
    try:
        print(f"sending verify_password({password})...")
        ack = await client.await_device_ack(common.build_verify_password(password))
        if ack is None:
            print(
                "VISUAL CHECK: no fa03 reply arrived within the timeout. Record: does "
                "verify_password produce no reply at all on this firmware, or only when "
                "no password is currently set on the device?"
            )
        else:
            print(
                f"VISUAL CHECK: raw fa03 ack = {ack.raw.hex()} (command_type={ack.command_type}, "
                f"command_subtype={ack.command_subtype}, accepted={ack.accepted}). Record this "
                "shape, and whether accepted flips between True/False when you re-run this "
                "with a correct vs. an incorrect password against a device with a known password set."
            )
    finally:
        await client.disconnect()
        print("disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("password", type=int, help="6-digit password to verify (0..999999)")
    parser.add_argument("--mac", default=None, help="device MAC address; omit to auto-discover")
    args = parser.parse_args()
    asyncio.run(main(args.mac, args.password))
