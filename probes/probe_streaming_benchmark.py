"""Streaming benchmark v2: color-coded phases, one bar color per phase.

v1 finding (2026-07-20, this panel): acked full frames = 1.35 fps; unacked
write-with-response bursts are NO faster (1.30 fps -- the with-response round
trip itself is the bottleneck); write-WITHOUT-response floods 171 fps into the
stack with zero acks and eventually killed the connection. What the panel
actually RENDERED per phase was impossible to attribute -- hence v2:

  PHASE 1  RED      acked baseline, 5 frames
  PHASE 2  GREEN    with-response burst, 10 frames, no ack waits
  PHASE 3  BLUE     WITHOUT-response burst, 50 frames flat out
  PHASE 4  YELLOW   paced  5 fps for 4s (without-response)
  PHASE 5  CYAN     paced 10 fps for 4s
  PHASE 6  MAGENTA  paced 15 fps for 4s
  PHASE 7  WHITE    paced 20 fps for 4s

Each phase: solid-color bar sweeping left-to-right, white progress strip on
row 0, then a black frame and a 3s gap. The operator reports per color:
smooth / choppy / a few steps / frozen / never appeared. Phases reconnect and
re-enter DIY mode if the previous phase killed the link.

Safety: DIY/image commands only. No password, no settings writes.

RESULT (2026-07-20, real 32x32, operator-observed): every phase rendered.
Wire: acked 1.25 fps; with-response burst 1.26 fps (the response round trip is
the bottleneck, not the ack wait); without-response burst ingested 167 fps;
paced 5/10/15/20 fps all sent on schedule but the device answered a flat ~7
notifies per 4s at every rate. Panel: 5..20 fps looked near-identical --
the device RENDERS full frames at a hard ~1.75 fps cap, samples the latest,
drops the rest; notifies track processed frames. Link died again at cleanup
after sustained flooding. Conclusion: unacked writes buy non-blocking sends,
not render rate; smooth animation belongs to the graffiti delta path.
"""

import asyncio
import sys
import time

from bleak import BleakClient, BleakError

sys.path.insert(0, __file__.rsplit("\\", 2)[0])  # repo root when run from probes/

from pyidotmatrix.protocol import image  # noqa: E402

ADDRESS = "6D:FD:F8:A0:3E:AF"
WRITE_UUID = "0000fa02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fa03-0000-1000-8000-00805f9b34fb"

SIZE = 32
FRAME_BYTES = SIZE * SIZE * 3

notify_count = 0


def on_notify(_h, _data: bytearray) -> None:
    global notify_count
    notify_count += 1


def make_frame(index: int, color: tuple[int, int, int]) -> bytes:
    """Solid-color 4px bar at (index % 32), white progress strip on row 0."""
    rgb = bytearray(FRAME_BYTES)
    bar_x = index % SIZE
    for y in range(SIZE):
        for dx in range(4):
            x = (bar_x + dx) % SIZE
            off = (y * SIZE + x) * 3
            rgb[off:off + 3] = bytes(color)
    for x in range((index % SIZE) + 1):
        rgb[x * 3:x * 3 + 3] = b"\xff\xff\xff"
    return bytes(rgb)


BLACK_FRAME = bytes(FRAME_BYTES)


async def send_frame(client: BleakClient, rgb: bytes, response: bool) -> None:
    for chunk in image.build_frame_packets(rgb):
        for packet in chunk:
            await client.write_gatt_char(WRITE_UUID, bytes(packet), response=response)


async def connect() -> BleakClient:
    client = BleakClient(ADDRESS, timeout=20.0)
    await client.connect()
    await client.start_notify(NOTIFY_UUID, on_notify)
    await asyncio.sleep(0.2)
    await client.write_gatt_char(WRITE_UUID, bytes(image.build_set_diy_mode(mode=1)), response=True)
    await asyncio.sleep(0.5)
    return client


async def ensure_alive(client: BleakClient | None) -> BleakClient:
    if client is not None and client.is_connected:
        return client
    print("  (link dead -- reconnecting + re-entering DIY)")
    if client is not None:
        try:
            await client.disconnect()
        except BleakError:
            pass
    await asyncio.sleep(1.5)
    return await connect()


async def phase_gap(client: BleakClient) -> None:
    """Black frame + pause so the next color change is unmistakable."""
    try:
        await send_frame(client, BLACK_FRAME, response=True)
    except BleakError:
        pass
    await asyncio.sleep(3.0)


async def main() -> None:
    global notify_count
    print(f"connecting to {ADDRESS} ...")
    client = await connect()
    print("connected, DIY mode entered (black flash).")
    await asyncio.sleep(1.0)

    # -- PHASE 1: RED, acked baseline ------------------------------------
    print("\nPHASE 1 RED: acked baseline, 5 frames")
    notify_count = 0
    t0 = time.perf_counter()
    for i in range(5):
        before = notify_count
        await send_frame(client, make_frame(i * 6, (255, 0, 0)), response=True)
        deadline = time.perf_counter() + 3.0
        while notify_count == before and time.perf_counter() < deadline:
            await asyncio.sleep(0.01)
    dt = time.perf_counter() - t0
    print(f"  {5 / dt:.2f} fps acked  (notifies {notify_count})")
    await phase_gap(client)

    # -- PHASE 2: GREEN, with-response burst -----------------------------
    print("\nPHASE 2 GREEN: with-response burst, 10 frames, no ack waits")
    client = await ensure_alive(client)
    notify_count = 0
    t0 = time.perf_counter()
    for i in range(10):
        await send_frame(client, make_frame(i * 3, (0, 255, 0)), response=True)
    dt = time.perf_counter() - t0
    print(f"  {10 / dt:.2f} fps sent  (notifies {notify_count})")
    await phase_gap(client)

    # -- PHASE 3: BLUE, without-response burst ---------------------------
    print("\nPHASE 3 BLUE: WITHOUT-response burst, 50 frames flat out")
    client = await ensure_alive(client)
    notify_count = 0
    t0 = time.perf_counter()
    try:
        for i in range(50):
            await send_frame(client, make_frame(i, (0, 80, 255)), response=False)
        dt = time.perf_counter() - t0
        print(f"  {50 / dt:.2f} fps sent  (notifies {notify_count})")
    except BleakError as ex:
        print(f"  burst aborted: {ex}")
    await asyncio.sleep(3.0)  # let the radio queue drain before judging the link
    await phase_gap(client)

    # -- PHASES 4-7: paced sweep, one color per rate ---------------------
    rates = (
        (5, (255, 220, 0), "YELLOW"),
        (10, (0, 255, 255), "CYAN"),
        (15, (255, 0, 255), "MAGENTA"),
        (20, (255, 255, 255), "WHITE"),
    )
    for phase_no, (target_fps, color, name) in enumerate(rates, start=4):
        print(f"\nPHASE {phase_no} {name}: paced {target_fps} fps for 4s (without-response)")
        client = await ensure_alive(client)
        notify_count = 0
        interval = 1.0 / target_fps
        sent = 0
        t0 = time.perf_counter()
        next_at = t0
        try:
            while time.perf_counter() - t0 < 4.0:
                await send_frame(client, make_frame(sent, color), response=False)
                sent += 1
                next_at += interval
                delay = next_at - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
            dt = time.perf_counter() - t0
            print(f"  sent {sent} in {dt:.2f}s = {sent / dt:.2f} fps  (notifies {notify_count})")
        except BleakError as ex:
            print(f"  aborted mid-phase: {ex}")
        await phase_gap(client)

    print("\ndone. quitting DIY (mode 2, keep last frame).")
    client = await ensure_alive(client)
    try:
        await client.write_gatt_char(WRITE_UUID, bytes(image.build_set_diy_mode(mode=2)), response=True)
        await client.stop_notify(NOTIFY_UUID)
        await client.disconnect()
    except BleakError as ex:
        print(f"  clean exit failed (harmless): {ex}")


if __name__ == "__main__":
    asyncio.run(main())
