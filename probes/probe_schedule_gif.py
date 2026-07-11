"""Hardware probe: Schedule per-theme gif upload (gifSolve).

EXPERIMENTAL: protocol/schedule.py's build_schedule_theme_packets bytes come
from decompiled-APK research (docs/ALARM_BUZZER_APK_FINDINGS.md in the research
lab), never exercised against real hardware. Same chunked-upload risk profile as
Timer's sendData (see probe_timer_image.py) -- no client method exists for this
yet, only builders + this probe.

The per-theme ack ([5,0,5,0x80,status]) numerically fits the driver's existing
DeviceAck shape (which is why response.py doesn't need a distinct type for it),
but the doc says its *status byte* carries the same 3-way vocabulary as Timer's
TimerAck (1 = next chunk, 3 = saved, else = error) -- DeviceAck's boolean
`accepted` field cannot represent that (only status=1 parses as accepted=True;
both 3 and 0 parse as accepted=False, indistinguishable from each other through
`.accepted` alone). This probe reads the raw status byte directly instead of
trusting `.accepted`, and that ambiguity is worth carrying back to the
architect regardless of what this probe observes.

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

from idotmatrix.client import IDotMatrixClient
from idotmatrix.protocol import schedule
from idotmatrix.protocol.response import DeviceAck
from idotmatrix.screen import ScreenSize

_CHUNK_ACK_TIMEOUT_SECONDS = 5.0
_ACTIVE_FOR_MINUTES = 2

# Per the doc: status 1 = proceed to next chunk, 3 = fully saved, else = error.
_STATUS_NEXT_CHUNK = 1
_STATUS_SAVED = 3


def _build_test_gif(size: int) -> bytes:
    """A tiny two-frame flashing gif (blue / green) -- generated in-memory so
    this probe needs no bundled fixture file."""
    frame_a = Image.new("P", (size, size))
    frame_a.putpalette([0, 0, 0] * 128 + [0, 0, 255] * 128)
    frame_a.paste(1, (0, 0, size, size))

    frame_b = Image.new("P", (size, size))
    frame_b.putpalette([0, 0, 0] * 128 + [0, 255, 0] * 128)
    frame_b.paste(1, (0, 0, size, size))

    buffer = io.BytesIO()
    frame_a.save(
        buffer, format="GIF", save_all=True, append_images=[frame_b], loop=0, duration=300, disposal=2
    )
    return buffer.getvalue()


def _print_ack(ack) -> None:
    if isinstance(ack, DeviceAck):
        print(
            f"[listener] DeviceAck: type={ack.command_type} subtype={ack.command_subtype} "
            f"accepted={ack.accepted} raw_status_byte={ack.raw[4]} raw={ack.raw.hex()}"
        )
    else:
        print(f"[listener] ack: {ack!r}")


async def _upload_theme(client: IDotMatrixClient, theme: schedule.ScheduleTheme, payload: bytes) -> bool:
    """Drives the per-theme upload handshake manually, reading the raw status
    byte (not `.accepted`) since DeviceAck's boolean can't carry the 3-way
    next-chunk/saved/failed vocabulary the doc claims this ack family uses."""
    chunks = schedule.build_schedule_theme_packets(theme, payload, schedule.CONTENT_GIF)
    acks: asyncio.Queue = asyncio.Queue()

    def _is_theme_ack(ack) -> bool:
        return isinstance(ack, DeviceAck) and ack.command_type == 5 and ack.command_subtype == 0x80

    unsubscribe = client.add_response_listener(lambda ack: acks.put_nowait(ack) if _is_theme_ack(ack) else None)
    try:
        for index, chunk in enumerate(chunks):
            is_last = index == len(chunks) - 1
            print(f"sending outer chunk {index + 1}/{len(chunks)} ({len(chunk)} BLE packets)...")
            await client._transport.write_packets([chunk], response=True)

            try:
                ack = await asyncio.wait_for(acks.get(), _CHUNK_ACK_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                print(
                    f"ABORT: no per-theme ack arrived within {_CHUNK_ACK_TIMEOUT_SECONDS}s after "
                    f"chunk {index + 1}/{len(chunks)}."
                )
                return False

            status = ack.raw[4]
            print(f"raw status byte = {status} (accepted={ack.accepted})")
            if status == _STATUS_SAVED:
                if not is_last:
                    print(
                        f"UNEXPECTED: status=SAVED after chunk {index + 1}/{len(chunks)}, "
                        "before the final chunk. Record this."
                    )
                return True
            if status == _STATUS_NEXT_CHUNK:
                if is_last:
                    print("UNEXPECTED: status=NEXT_CHUNK after what should be the final chunk.")
                continue
            print(f"ABORT: status={status} does not match next-chunk(1)/saved(3); treating as error.")
            return False

        print("ABORT: ran out of chunks without ever seeing status=SAVED.")
        return False
    finally:
        unsubscribe()


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
        saved = await _upload_theme(client, theme, payload)
        if not saved:
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
