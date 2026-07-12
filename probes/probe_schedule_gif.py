"""Hardware probe: Schedule per-theme gif upload (gifSolve).

HARDWARE-CONFIRMED 2026-07-12 on a real 32x32 panel: the per-theme upload
handshake works, and its ack ([5,0,5,0x80,status]) carries the same 3-way
status vocabulary as Timer's sendData (1 = next chunk, 3 = saved, 0 = failed)
-- see protocol/response.py's StatusAck. A real upload completed with
status=SAVED; that success is what motivated dispatching this ack family as
StatusAck instead of a plain DeviceAck, since the old DeviceAck path parsed a
SUCCESSFUL save (status=3) as accepted=False and logged a spurious "device
rejected" warning. This probe now drives the upload through
client.experimental.schedule_set_theme (see client.py / _send_chunked_upload)
instead of a hand-rolled handshake.

Runs the master switch on first (buzzer off, to isolate the schedule item
itself), then uploads one small generated two-frame gif as a theme active for
the next couple of minutes so its effect can be observed live.

Usage:
    python probes/probe_schedule_gif.py [--mac AA:BB:CC:DD:EE:FF] [--index 0]

Not run in CI -- no hardware access exists in the dev environment this was
written in. A human runs this with a real panel in view and records what they
observe at each VISUAL CHECK line.
"""

import argparse
import asyncio
import io
from datetime import datetime, timedelta

from PIL import Image

from idotmatrix.client import ChunkedUploadError, IDotMatrixClient
from idotmatrix.protocol import schedule
from idotmatrix.protocol.response import DeviceAck, StatusAck
from idotmatrix.screen import ScreenSize

_ACTIVE_FOR_MINUTES = 2


def _build_test_gif(size: int) -> bytes:
    """A tiny two-frame flashing gif (solid blue, then solid green) --
    generated in-memory so this probe needs no bundled fixture file.

    Built as RGB frames and left to Pillow's own palettization on save, the
    same GIF path protocol/gif.py's adapt_gif and probe_timer_image.py's
    checkerboard both use. A PREVIOUS version of this probe built P-mode
    frames by hand with putpalette([black]*128 + [color]*128) and
    paste(1, ...) to fill the frame -- but palette index 1 falls in the
    BLACK half of both palettes (the blue/green entries only start at index
    128), so hardware displayed an all-black GIF instead of the intended
    flashing color (HARDWARE-CONFIRMED bug, 2026-07-12). RGB frames sidestep
    that class of bug entirely.
    """
    frame_a = Image.new("RGB", (size, size), (0, 0, 255))  # solid blue
    frame_b = Image.new("RGB", (size, size), (0, 255, 0))  # solid green

    buffer = io.BytesIO()
    frame_a.save(
        buffer,
        format="GIF",
        save_all=True,
        optimize=True,  # required: disabling it breaks the transfer (see protocol/gif.py)
        append_images=[frame_b],
        loop=0,
        duration=300,
        disposal=2,
    )
    return buffer.getvalue()


def _print_ack(ack) -> None:
    if isinstance(ack, StatusAck):
        print(
            f"[listener] StatusAck: type={ack.command_type} subtype={ack.command_subtype} "
            f"status={ack.status} raw={ack.raw.hex()}"
        )
    elif isinstance(ack, DeviceAck):
        print(
            f"[listener] DeviceAck: type={ack.command_type} subtype={ack.command_subtype} "
            f"accepted={ack.accepted} raw={ack.raw.hex()}"
        )
    else:
        print(f"[listener] ack: {ack!r}")


async def main(mac: str | None, index: int) -> None:
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, mac_address=mac)
    client.add_response_listener(_print_ack)  # attached before any send, per convention

    print("connecting...")
    await client.connect()
    try:
        print("\n--- schedule_master_switch(enable=True, buzzer=False) ---")
        await client.experimental.schedule_master_switch(enable=True, buzzer=False)
        print("VISUAL CHECK: record any visible schedule-enabled indicator on the panel.")
        input("Press Enter to continue...")

        now = datetime.now()
        end = now + timedelta(minutes=_ACTIVE_FOR_MINUTES)
        theme = schedule.ScheduleTheme(
            index=index,
            week=0xFF,  # unpatched raw bitmask; guessed as "every day", unverified (see patch_week)
            start_hour=now.hour,
            start_min=now.minute,
            end_hour=end.hour,
            end_min=end.minute,
        )
        payload = _build_test_gif(client.screen_size.width)
        print(
            f"\n--- uploading theme {index}, active window "
            f"{now.strftime('%H:%M')}-{end.strftime('%H:%M')} ---"
        )
        try:
            await client.experimental.schedule_set_theme(theme, payload, schedule.CONTENT_GIF)
        except ChunkedUploadError as ex:
            print(f"ABORT: {ex}")
            print("Upload did not complete; nothing more to observe.")
            return

        print(
            "\nUpload acknowledged as SAVED. Since the active window starts now, watch the "
            "panel immediately."
        )
        print(
            "VISUAL CHECK: does the panel show the blue/green flashing pattern right now? "
            f"Does it stop showing it after {end.strftime('%H:%M')} (window end)? Does the day "
            "it's active on match what you'd expect from week=0xFF (every day) after patch_week's "
            "transform -- or does patch_week's bit-rotate make it fire on the wrong day?"
        )
        input("Press Enter to finish...")
    finally:
        await client.disconnect()
        print("disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", default=None, help="device MAC address; omit to auto-discover")
    parser.add_argument("--index", type=int, default=0, help="schedule theme index to upload")
    args = parser.parse_args()
    asyncio.run(main(args.mac, args.index))
