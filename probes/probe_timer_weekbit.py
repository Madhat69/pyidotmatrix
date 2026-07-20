"""Timer week-bit day mapping, verified WITHOUT waiting for real days.

Hypothesis under test (protocol/timer.py, from TimerAgreement.java bit math):
week bit0 = enable, bit1 = Monday .. bit7 = Sunday, i.e. weekday d (Monday=0)
maps to bit (d + 1). Before tonight only "a fire happened on a Sunday with
week=0xFF" existed as evidence -- which proves nothing about the mapping.

Trick: the device checks the mask against its OWN RTC weekday, and we control
the RTC via set_time. Three tests, all in ~9 minutes:

  A. Real time, timer masked to TODAY's bit only        -> must FIRE
  B. RTC spoofed to TOMORROW (same wall time), same mask -> must NOT fire
  C. Still spoofed, timer masked to TOMORROW's bit only  -> must FIRE

A+C firing while B stays silent pins the mapping for two adjacent days and
confirms the device evaluates mask-vs-RTC-weekday; with the +1 bit shift
structure from the decompile, that verifies the whole table.

Buzzer sounds ~10s on A and C (DURATION_10S). Real time restored and the
slot closed at the end.
"""

import asyncio
import io
from datetime import datetime, timedelta

from PIL import Image

from pyidotmatrix import IDotMatrixClient, ScreenSize
from pyidotmatrix.protocol import timer

ADDRESS = "6D:FD:F8:A0:3E:AF"
SLOT = 0


def build_test_gif(size: int) -> bytes:
    """2-frame checkerboard, the CONTENT_GIF encoding hardware-confirmed to
    render at fire time (probe_timer_image.py, 2026-07-12)."""
    frame_a = Image.new("RGB", (size, size))
    frame_b = Image.new("RGB", (size, size))
    pa, pb = frame_a.load(), frame_b.load()
    for y in range(size):
        for x in range(size):
            on = (x // 4 + y // 4) % 2 == 0
            pa[x, y] = (255, 255, 0) if on else (200, 0, 0)
            pb[x, y] = (200, 0, 0) if on else (255, 255, 0)
    buf = io.BytesIO()
    frame_a.save(buf, format="GIF", save_all=True, optimize=True,
                 append_images=[frame_b], loop=0, duration=500, disposal=2)
    return buf.getvalue()


def make_timer(week: int, fire_at: datetime) -> timer.Timer:
    return timer.Timer(
        num=SLOT, week=week, hour=fire_at.hour, minute=fire_at.minute,
        duration_bucket=timer.DURATION_10S, content_type=timer.CONTENT_GIF,
        buzzer_enable=True,
    )


async def arm_and_wait(client: IDotMatrixClient, payload: bytes, week: int,
                       device_now: datetime, label: str, expect: str) -> None:
    fire_at = device_now + timedelta(seconds=75)
    t = make_timer(week, fire_at)
    await client.experimental.timer_set(t, payload)
    wait_s = 75 + 40  # to fire time, plus its "clock first, then content" grace
    print(f"{label}: armed slot {SLOT} week=0b{week:08b} for device-time "
          f"{fire_at.strftime('%H:%M')} -- EXPECT {expect}. waiting ~{wait_s}s ...",
          flush=True)
    await asyncio.sleep(wait_s)
    print(f"{label}: window over. << operator: did it fire (checkerboard + buzzer)?",
          flush=True)
    await client.experimental.timer_close(t)


async def main() -> None:
    payload = None
    print(f"connecting to {ADDRESS} ...", flush=True)
    async with IDotMatrixClient.connect_to(ADDRESS, ScreenSize.SIZE_32x32) as client:
        payload = build_test_gif(client.screen_size.width)

        real_now = datetime.now()
        today_bit = 1 << (real_now.weekday() + 1)
        tomorrow = real_now + timedelta(days=1)
        tomorrow_bit = 1 << (tomorrow.weekday() + 1)
        enable = 1  # bit0

        print(f"real time {real_now:%A %H:%M:%S}: today bit={today_bit:#04x}, "
              f"tomorrow ({tomorrow:%A}) bit={tomorrow_bit:#04x}", flush=True)

        # A: real time, today's bit -> must fire
        await client.common.set_time(datetime.now())  # make sure RTC matches host
        await arm_and_wait(client, payload, enable | today_bit,
                           datetime.now(), "TEST A (today's bit, real day)", "FIRE")

        # B: spoof tomorrow, same today-bit mask -> must NOT fire
        fake = datetime.now() + timedelta(days=1)
        await client.common.set_time(fake)
        print(f"RTC spoofed to {fake:%A %H:%M:%S}", flush=True)
        await arm_and_wait(client, payload, enable | today_bit,
                           fake, "TEST B (today's bit, fake tomorrow)", "NO FIRE")

        # C: still spoofed tomorrow, tomorrow's bit -> must fire
        fake2 = datetime.now() + timedelta(days=1)
        await client.common.set_time(fake2)  # resync fake clock before arming
        await arm_and_wait(client, payload, enable | tomorrow_bit,
                           fake2, "TEST C (tomorrow's bit, fake tomorrow)", "FIRE")

        # restore reality
        await client.common.set_time(datetime.now())
        print("RTC restored to real time; slot closed after each test. done.", flush=True)
        await client.clock.show()


if __name__ == "__main__":
    asyncio.run(main())
