"""Graffiti byte-4 ("moveType") sweep.

Our graffiti header is [len_lo, len_hi, 5, mirror, UNKNOWN=0, r, g, b] + coords.
Byte 3 (mirror) was swept 2026-07-12 (0/1/2/4 identical, 3 nacked). Byte 4 has
only ever been sent as 0. The APK's real-time paint sender carries its variable
"option"/move-type byte at this offset (SendCore.sendDiyImageData, 5-byte
header envelope -- APK_SECOND_PASS.md Q5c), and LumiSync's RE doc names the
same offset "moveType" (docs/idotmatrix-ble-research.md). If it shifts or
animates drawn content, it is a free scroll primitive for the delta path.

Plan: DIY mode 1 (clear), then five identical 6x6 squares, one per byte-4
value 0..4, each a different color in a different spot, 2.5s apart. The
operator reports any square that moves, shifts, mirrors, or fails to appear.

Safety: graffiti + DIY-mode commands only.
"""

import asyncio

from bleak import BleakClient

ADDRESS = "6D:FD:F8:A0:3E:AF"
WRITE_UUID = "0000fa02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fa03-0000-1000-8000-00805f9b34fb"

DIY_MODE_1 = bytes([5, 0, 4, 1, 1])

CASES = [
    (0, (255, 0, 0), (2, 2), "RED    top-left"),
    (1, (0, 255, 0), (24, 2), "GREEN  top-right"),
    (2, (0, 128, 255), (2, 24), "BLUE   bottom-left"),
    (3, (255, 220, 0), (24, 24), "YELLOW bottom-right"),
    (4, (255, 0, 255), (13, 13), "MAGENTA center"),
]


def square(color: tuple[int, int, int], origin: tuple[int, int], byte4: int) -> bytearray:
    xys = [(origin[0] + dx, origin[1] + dy) for dy in range(6) for dx in range(6)]
    size = 8 + 2 * len(xys)
    payload = bytearray([size % 256, size // 256, 5, 1, byte4, *color])
    for x, y in xys:
        payload += bytes((x, y))
    return payload


async def main() -> None:
    notifies: list[bytes] = []

    def on_notify(_h, data: bytearray) -> None:
        notifies.append(bytes(data))

    print(f"connecting to {ADDRESS} ...")
    async with BleakClient(ADDRESS, timeout=20.0) as client:
        await client.start_notify(NOTIFY_UUID, on_notify)
        await asyncio.sleep(0.2)
        print("entering DIY mode 1 (black flash) ...")
        await client.write_gatt_char(WRITE_UUID, DIY_MODE_1, response=True)
        await asyncio.sleep(1.0)

        for byte4, color, origin, label in CASES:
            notifies.clear()
            print(f"byte4={byte4}: {label}")
            await client.write_gatt_char(
                WRITE_UUID, bytes(square(color, origin, byte4)), response=True
            )
            await asyncio.sleep(2.5)
            print(f"  notifies: {[n.hex() for n in notifies] or 'none (normal for graffiti)'}")

        print("\nall five sent. leaving squares on screen for observation.")
        await client.stop_notify(NOTIFY_UUID)


if __name__ == "__main__":
    asyncio.run(main())
