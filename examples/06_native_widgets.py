"""Tours four native, device-rendered widgets: countdown, stopwatch
(chronograph), scoreboard, and scrolling text.

What this shows:
    - client.countdown.start/pause/restart/stop() -- runs autonomously on
      the device, auto-returns to the clock at zero
    - client.chronograph.reset/start/pause/resume() -- counts up on the
      device; NOTE start-after-pause restarts from zero, it does not resume
      (hardware-observed, see docs/features.md#chronograph--stopwatch)
    - client.scoreboard.show() -- a two-digit-per-side score display
    - client.text.show() -- device-rendered scrolling text; requires a TTF
      font file supplied by the caller (there is no bundled font)

Only one native mode is active on the panel at a time, so each widget below
replaces the previous one -- that's a firmware property, not an SDK quirk.

Hardware needed: one iDotMatrix panel. A TTF font path is optional -- pass one
to include the text demo, otherwise that step is skipped:

    python examples/06_native_widgets.py AA:BB:CC:DD:EE:FF
    python examples/06_native_widgets.py AA:BB:CC:DD:EE:FF /path/to/font.ttf
"""

import asyncio
import sys

from pyidotmatrix import DeviceInfo, IDotMatrixClient, ScreenSize, discover
from pyidotmatrix.protocol import text


async def resolve_device() -> DeviceInfo | str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    devices = await discover()
    if not devices:
        raise SystemExit("No iDotMatrix panel found and no address given.")
    return devices[0]


async def demo_countdown(client: IDotMatrixClient) -> None:
    print("countdown: starting a 10s timer ...")
    await client.countdown.start(minutes=0, seconds=10)
    await asyncio.sleep(4)
    print("countdown: pausing ...")
    await client.countdown.pause()
    await asyncio.sleep(2)
    print("countdown: stopping early ...")
    await client.countdown.stop()


async def demo_chronograph(client: IDotMatrixClient) -> None:
    print("chronograph: reset + start (counting up) ...")
    await client.chronograph.reset()
    await client.chronograph.start()
    await asyncio.sleep(3)
    print("chronograph: pause ...")
    await client.chronograph.pause()
    await asyncio.sleep(1)
    # Caveat (hardware-observed, not an SDK bug): this restarts from zero
    # rather than resuming from where it paused.
    print("chronograph: resume() -- actually restarts from zero on this firmware ...")
    await client.chronograph.resume()
    await asyncio.sleep(2)


async def demo_scoreboard(client: IDotMatrixClient) -> None:
    print("scoreboard: 12 : 34 ...")
    await client.scoreboard.show(count1=12, count2=34)
    await asyncio.sleep(3)


async def demo_text(client: IDotMatrixClient, font_path: str) -> None:
    print(f"text: scrolling HELLO using font {font_path} ...")
    await client.text.show(
        "HELLO",
        font_path=font_path,
        font_size=16,
        text_mode=text.MODE_MARQUEE,
        speed=95,               # 100 measured smoothest on a 32x32 panel
        color_mode=text.COLOR_RGB,
        color=(0, 200, 255),
    )
    await asyncio.sleep(5)


async def main() -> None:
    device = await resolve_device()
    font_path = sys.argv[2] if len(sys.argv) > 2 else None

    async with IDotMatrixClient.connect_to(device, ScreenSize.SIZE_32x32) as client:
        await demo_countdown(client)
        await demo_chronograph(client)
        await demo_scoreboard(client)
        if font_path:
            await demo_text(client, font_path)
        else:
            print("no font path given (argv[2]) -- skipping the text demo.")
        print("done -- restoring the clock.")
        await client.clock.show()


if __name__ == "__main__":
    asyncio.run(main())
