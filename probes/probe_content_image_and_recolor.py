"""Two M3 leftovers in one run: Timer CONTENT_IMAGE = PNG hypothesis, and the
byte4=2 single-pixel recolor exploit.

CONTENT_IMAGE: raw RGB is SAVED but never renders (2026-07-12). Schedule's
image content is PNG (APK_SECOND_PASS.md Q2) -- so try PNG here too. Buzzer on:
buzzer+image = solved; buzzer+no-image = PNG wrong too.

byte4=2 exploit: if a 1-pixel byte4=2 command recolors the 36-pixel square
from two commands back, the recolor primitive is real and nearly free.
"""

import asyncio
import io
from datetime import datetime, timedelta

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import timer

ADDRESS = "6D:FD:F8:A0:3E:AF"
SLOT = 0


def stripes_png(size: int) -> bytes:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = (0, 128, 255) if ((x + y) // 4) % 2 == 0 else (255, 255, 255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def square(color, origin, byte4, coords=None):
    xys = coords if coords is not None else [
        (origin[0] + dx, origin[1] + dy) for dy in range(6) for dx in range(6)
    ]
    size = 8 + 2 * len(xys)
    p = bytearray([size % 256, size // 256, 5, 1, byte4, *color])
    for x, y in xys:
        p += bytes((x, y))
    return p


async def main() -> None:
    print(f"connecting to {ADDRESS} ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        fire_at = datetime.now() + timedelta(seconds=100)
        t = timer.Timer(
            num=SLOT, week=0xFF, hour=fire_at.hour, minute=fire_at.minute,
            duration_bucket=timer.DURATION_10S, content_type=timer.CONTENT_IMAGE,
            buzzer_enable=True,
        )
        await client.common.set_time(datetime.now())
        await client.experimental.timer_set(t, stripes_png(32))
        print(f"alarm armed: CONTENT_IMAGE + PNG payload, fires {fire_at:%H:%M} "
              "(buzzer will sound)", flush=True)

        print("meanwhile: byte4 exploit test in 5s ...", flush=True)
        await asyncio.sleep(5)
        await client.transport_write(square((255, 0, 0), (2, 2), 0)) if False else None
        write = client.graffiti._send
        await write(bytearray([5, 0, 4, 1, 1]))  # DIY mode 1, clear
        await asyncio.sleep(1)
        await write(square((255, 0, 0), (2, 2), 0))
        print("A: RED 6x6 square top-left (3s)", flush=True)
        await asyncio.sleep(3)
        await write(square((0, 255, 0), (24, 2), 0))
        print("B: GREEN 6x6 square top-right (3s)", flush=True)
        await asyncio.sleep(3)
        await write(square((255, 0, 255), None, 2, coords=[(15, 28)]))
        print("C: ONE magenta pixel bottom-center with byte4=2", flush=True)
        print("   << did the RED square (two back) turn MAGENTA? (10s)", flush=True)
        await asyncio.sleep(10)

        remaining = (fire_at - datetime.now()).total_seconds() + 40
        print(f"now waiting ~{remaining:.0f}s for the alarm "
              "<< buzzer + BLUE/WHITE DIAGONAL STRIPES = CONTENT_IMAGE solved; "
              "buzzer + no stripes = still broken", flush=True)
        await asyncio.sleep(max(remaining, 5))

        await client.experimental.timer_close(t)
        await client.clock.show()
        print("slot closed, clock restored. done.", flush=True)


asyncio.run(main())
