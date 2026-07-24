"""Discovers a nearby iDotMatrix panel, connects, and shows the native clock.

What this shows:
    - discover() for finding panels by BLE advertisement name ("IDM-*")
    - IDotMatrixClient.connect_to() as an async context manager
    - client.clock.show() -- the device renders the clock face itself

Hardware needed: one iDotMatrix panel, powered on and in BLE range. Pass its
MAC address as argv[1] to skip discovery (useful once you know it):

    python examples/01_discover_and_clock.py
    python examples/01_discover_and_clock.py AA:BB:CC:DD:EE:FF
"""

import asyncio
import sys

from pyidotmatrix import DeviceInfo, IDotMatrixClient, ScreenSize, discover


async def resolve_device() -> DeviceInfo | str:
    """argv[1] if given, otherwise the first panel discover() finds.

    discover() never raises for "nothing found" -- it returns an empty list --
    so the caller (here) is responsible for turning that into a clear exit.
    """
    if len(sys.argv) > 1:
        return sys.argv[1]

    print("No address on argv[1]; scanning for iDotMatrix panels...")
    devices = await discover()
    if not devices:
        raise SystemExit(
            "No iDotMatrix panel found. Power one on nearby, or pass its MAC "
            "address directly: python 01_discover_and_clock.py AA:BB:CC:DD:EE:FF"
        )
    device = devices[0]
    print(f"Found {device.name} ({device.address}, rssi={device.rssi})")
    return device


async def main() -> None:
    device = await resolve_device()

    # ScreenSize must match the physical panel -- the driver has no way to ask
    # the device its own size. This gallery assumes the common 32x32 panel;
    # change this if yours is a different size.
    async with IDotMatrixClient.connect_to(device, ScreenSize.SIZE_32x32) as client:
        print("connected -- showing the native clock face")
        # verify_commands defaults to True: a nack here would raise
        # CommandRejectedError rather than fail silently.
        await client.clock.show(hour24=True, show_date=True, color=(255, 255, 255))
        print("clock is showing. Leaving it running for 10s before disconnecting...")
        await asyncio.sleep(10)
        # Disconnecting doesn't clear the clock -- it ticks on through
        # disconnects (the device's own RTC), just not across a power-cycle.


if __name__ == "__main__":
    asyncio.run(main())
