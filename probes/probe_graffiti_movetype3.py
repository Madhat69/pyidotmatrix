"""Graffiti byte4=2: FIFO vs two-back discriminator.

Three byte4=0 squares (red, green, blue in draw order), then one yellow with
byte4=2. FIFO-recolor predicts RED (oldest) recolors; a relative two-commands-
back reference predicts GREEN.

RESULT (2026-07-20, real 32x32, operator-observed): GREEN turned yellow --
byte4=2 recolors the command exactly TWO back. Positional, reproduced 3/3
across probe_graffiti_movetype{,2,3}.py.
"""

import asyncio

from bleak import BleakClient

ADDRESS = "6D:FD:F8:A0:3E:AF"
WRITE_UUID = "0000fa02-0000-1000-8000-00805f9b34fb"


def square(color, origin, byte4):
    xys = [(origin[0] + dx, origin[1] + dy) for dy in range(6) for dx in range(6)]
    size = 8 + 2 * len(xys)
    p = bytearray([size % 256, size // 256, 5, 1, byte4, *color])
    for x, y in xys:
        p += bytes((x, y))
    return p

STEPS = [
    (0, (255, 0, 0), (2, 2), "1. RED top-left, byte4=0"),
    (0, (0, 255, 0), (24, 2), "2. GREEN top-right, byte4=0"),
    (0, (0, 128, 255), (2, 24), "3. BLUE bottom-left, byte4=0"),
    (2, (255, 220, 0), (24, 24), "4. YELLOW bottom-right, byte4=2  << red=FIFO, green=two-back?"),
]

async def main():
    print(f"connecting to {ADDRESS} ...")
    async with BleakClient(ADDRESS, timeout=20.0) as client:
        print("entering DIY mode 1 (black flash) ...")
        await client.write_gatt_char(WRITE_UUID, bytes([5, 0, 4, 1, 1]), response=True)
        await asyncio.sleep(1.0)
        for byte4, color, origin, label in STEPS:
            print(label)
            await client.write_gatt_char(WRITE_UUID, bytes(square(color, origin, byte4)), response=True)
            await asyncio.sleep(4.0)
        print("done.")

asyncio.run(main())
