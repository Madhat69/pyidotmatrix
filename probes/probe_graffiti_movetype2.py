"""Graffiti byte-4=2 recolor semantics: what exactly gets repainted?

Probe 1 (probe_graffiti_movetype.py, this panel, 2026-07-20): a byte4=2
command drew its own pixels AND recolored the earlier byte4=0 red square to
its blue. Values 0/1/3/4 showed no such side effect. This probe pins down the
scope: first drawing, previous drawing, or all prior graffiti pixels.

Sequence (operator narrates after each step):
  1. RED square top-left, byte4=0
  2. GREEN square top-right, byte4=0
  3. BLUE square bottom-left, byte4=2   -> which of red/green recolor?
  4. YELLOW square bottom-right, byte4=2 -> which of the three recolor?

RESULT (2026-07-20, real 32x32, operator-observed): step 3 appeared to
recolor RED, step 4 GREEN -- read then as a positional two-back reference.

CORRECTION (2026-07-21, probe_graffiti_transform.py): byte4=2 is
VERTICAL_MIRROR. The bottom-row squares mirrored onto the top-row squares'
exact positions, overpainting them -- no recoloring ever happened. See
probe_graffiti_movetype3.py's correction note.
"""

import asyncio

from bleak import BleakClient

ADDRESS = "6D:FD:F8:A0:3E:AF"
WRITE_UUID = "0000fa02-0000-1000-8000-00805f9b34fb"

DIY_MODE_1 = bytes([5, 0, 4, 1, 1])

STEPS = [
    (0, (255, 0, 0), (2, 2), "1. RED top-left, byte4=0"),
    (0, (0, 255, 0), (24, 2), "2. GREEN top-right, byte4=0"),
    (2, (0, 128, 255), (2, 24), "3. BLUE bottom-left, byte4=2  << watch red+green"),
    (2, (255, 220, 0), (24, 24), "4. YELLOW bottom-right, byte4=2  << watch all three"),
]


def square(color: tuple[int, int, int], origin: tuple[int, int], byte4: int) -> bytearray:
    xys = [(origin[0] + dx, origin[1] + dy) for dy in range(6) for dx in range(6)]
    size = 8 + 2 * len(xys)
    payload = bytearray([size % 256, size // 256, 5, 1, byte4, *color])
    for x, y in xys:
        payload += bytes((x, y))
    return payload


async def main() -> None:
    print(f"connecting to {ADDRESS} ...")
    async with BleakClient(ADDRESS, timeout=20.0) as client:
        print("entering DIY mode 1 (black flash) ...")
        await client.write_gatt_char(WRITE_UUID, DIY_MODE_1, response=True)
        await asyncio.sleep(1.0)
        for byte4, color, origin, label in STEPS:
            print(label)
            await client.write_gatt_char(
                WRITE_UUID, bytes(square(color, origin, byte4)), response=True
            )
            await asyncio.sleep(4.0)
        print("done. squares left on screen.")


if __name__ == "__main__":
    asyncio.run(main())
