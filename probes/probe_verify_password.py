"""Hardware probe: verify_password ack shape.

build_verify_password's bytes are confirmed from the APK, but the shape of the
device's reply was never observed (see docs/APK_PROTOCOL_FINDINGS.md, finding #1).
This probe sends it and prints the raw fa03 ack bytes so that shape can be
recorded -- ideally run twice: once with a password that matches one already set
via client.device.set_password(), and once with a wrong one, to see whether
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


_INTERLOCK = "--i-accept-the-lockout-risk"

_REFUSAL = f"""
REFUSING TO RUN.

This probe sends verify_password to real hardware, and the password commands are
sequenced LAST across the entire roadmap by maintainer ruling (docs/ROADMAP.md
section 17, SDK-M3) -- after every other milestone's hardware work is done.

Why the ruling exists:
  * there is NO known factory-reset path on this device;
  * set_password's byte 4 is a MODE field that is a variable in the vendor app
    and hardcoded to 1 by us, explicitly unexplored -- that, not the password
    value, is the real unknown;
  * verify_password's ack key (5, 2) collides byte-for-byte with graffiti's
    nack, so even READING whether authentication succeeded is unreliable;
  * the reference panel is the only one this project has.

Before this is ever run, do the zero-risk step first: open the vendor app and
confirm it exposes password set AND clear for this panel. If it can clear one,
the worst case becomes "unlock with the app". If it cannot, do not run this.

If you are the maintainer, every other milestone is genuinely finished, and you
accept that you may lock the panel out of its own driver permanently, re-run
with {_INTERLOCK} as the last argument.
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("password", type=int, help="6-digit password to verify (0..999999)")
    parser.add_argument("--mac", default=None, help="device MAC address; omit to auto-discover")
    parser.add_argument(
        _INTERLOCK,
        dest="accepted_risk",
        action="store_true",
        help="required acknowledgement; without it this probe refuses to run",
    )
    args = parser.parse_args()
    if not args.accepted_risk:
        print(_REFUSAL)
        raise SystemExit(2)
    asyncio.run(main(args.mac, args.password))
