"""Hardware probe: Schedule masterSwitch (weekly-schedule on/off + buzzer).

EXPERIMENTAL: protocol/schedule.py's build_master_switch bytes come from
decompiled-APK research (docs/ALARM_BUZZER_APK_FINDINGS.md in the research lab),
never exercised against real hardware. This is the smallest, flattest command in
the Timer/Schedule subsystem (5 bytes, no chunking), and its ack shape
([5,0,7,0x80,status]) already matches the driver's existing DeviceAck parser --
so this probe is also step 1 of confirming that endianness/ack assumptions
transfer before touching anything chunked (Timer sendData / Schedule theme
upload).

Sends all four enable/buzzer combinations in turn and prints the raw fa03 ack
after each. The bit-packing (packed = (buzzer << 1) | enable) is derived from a
decompiled bit packer, not observed on a real device -- record whatever the
device visibly does (if the panel shows a schedule indicator) alongside the ack.

Usage:
    python probes/probe_schedule_master_switch.py [--mac AA:BB:CC:DD:EE:FF]

Not run in CI -- no hardware access exists in the dev environment this was
written in. A human runs this with a real device and records what they observe
at each VISUAL CHECK line.
"""

import argparse
import asyncio

from pyidotmatrix.client import IDotMatrixClient
from pyidotmatrix.protocol import schedule
from pyidotmatrix.screen import ScreenSize

_COMBINATIONS = [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
]


def _print_ack(ack) -> None:
    print(
        f"[listener] ack: type={ack.command_type} subtype={ack.command_subtype} "
        f"accepted={ack.accepted} raw={ack.raw.hex()}"
    )


async def main(mac: str | None) -> None:
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, mac_address=mac)
    client.add_response_listener(_print_ack)  # attached before any send, per convention

    print("connecting...")
    await client.connect()
    try:
        for enable, buzzer in _COMBINATIONS:
            print(f"\n--- schedule_master_switch(enable={enable}, buzzer={buzzer}) ---")
            command = schedule.build_master_switch(enable, buzzer)
            print(f"sending {command.hex()}...")
            ack = await client.await_device_ack(command)
            if ack is None:
                print(
                    "VISUAL CHECK: no fa03 reply arrived within the timeout. Record: does "
                    "masterSwitch produce no ack at all on this firmware, contrary to the doc's "
                    "claim that it matches the standard DeviceAck shape?"
                )
            else:
                print(
                    f"VISUAL CHECK: raw fa03 ack = {ack.raw.hex()} (command_type={ack.command_type}, "
                    f"command_subtype={ack.command_subtype}, accepted={ack.accepted}). Expected shape "
                    "is [5,0,7,0x80,status]. Record whether accepted flips as expected, and whether "
                    "the panel shows any visible schedule-enabled indicator."
                )
            input("Press Enter to try the next combination...")
    finally:
        await client.disconnect()
        print("disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", default=None, help="device MAC address; omit to auto-discover")
    args = parser.parse_args()
    asyncio.run(main(args.mac))
