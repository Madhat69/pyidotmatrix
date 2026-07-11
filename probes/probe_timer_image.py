"""Hardware probe: Timer sendData (chunked custom-content alarm upload).

HARDWARE-CONFIRMED 2026-07-12 on a real 32x32 panel: Timer's sendData/
sendCloseData handshake works, and content must be an encoded file -- a real
GIF bytestream with CONTENT_GIF renders at fire time (animated, plays for the
full duration, buzzer works). Raw RGB frame bytes with CONTENT_IMAGE are
accepted and saved (TimerAck status=3 SAVED) but do NOT render -- the panel
just shows the clock. This probe therefore uploads a small 2-frame animated
GIF with CONTENT_GIF, the combination proven to render, mirroring how
protocol/gif.py prepares its own GIF payloads. What CONTENT_IMAGE actually
expects instead is still unknown.

Also confirmed: a single-chunk upload goes straight to TimerAck status=3
SAVED (no status=1 NEXT_CHUNK first), TimerAck frames can arrive DUPLICATED,
and at fire time the panel shows the clock for a few seconds before the
alarm's content appears -- don't be alarmed if the checkerboard doesn't pop
up instantly at the scheduled minute.

Sets a real alarm 2 minutes in the future on the given slot, with a small
generated 2-frame animated GIF as its content and the buzzer on, then tells
the human what to watch for at fire time.

Usage:
    python probes/probe_timer_image.py [--mac AA:BB:CC:DD:EE:FF] [--slot 0]

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
from idotmatrix.protocol import timer
from idotmatrix.protocol.response import TIMER_STATUS_FAILED, TIMER_STATUS_NEXT_CHUNK, TIMER_STATUS_SAVED, TimerAck
from idotmatrix.screen import ScreenSize

_CHUNK_ACK_TIMEOUT_SECONDS = 5.0
_FIRE_IN_MINUTES = 2
_FRAME_DURATION_MS = 500


def _build_test_gif(size: int) -> bytes:
    """A 2-frame yellow/red checkerboard swap -- easy to recognize as the
    alarm's own content (distinct from whatever was on the panel before it
    fired) and animated, so it's obvious on the panel that it's really
    playing a GIF and not a static image. Encoded the same way
    protocol/gif.py's adapt_gif does it: PIL save to BytesIO, format GIF,
    save_all, optimize, loop=0, disposal=2 -- this is the exact combination
    hardware confirmed the device will render for a Timer's CONTENT_GIF.
    """
    frame_a = Image.new("RGB", (size, size))
    frame_b = Image.new("RGB", (size, size))
    pixels_a = frame_a.load()
    pixels_b = frame_b.load()
    for y in range(size):
        for x in range(size):
            on_a = (x // 4 + y // 4) % 2 == 0
            pixels_a[x, y] = (255, 255, 0) if on_a else (200, 0, 0)
            pixels_b[x, y] = (200, 0, 0) if on_a else (255, 255, 0)

    buffer = io.BytesIO()
    frame_a.save(
        buffer,
        format="GIF",
        save_all=True,
        optimize=True,  # required: disabling it breaks the transfer (see protocol/gif.py)
        append_images=[frame_b],
        loop=0,
        duration=_FRAME_DURATION_MS,
        disposal=2,
    )
    return buffer.getvalue()


def _print_ack(ack) -> None:
    if isinstance(ack, TimerAck):
        print(f"[listener] TimerAck: status={ack.status} raw={ack.raw.hex()}")
    else:
        print(f"[listener] ack: {ack!r}")


async def _upload_timer_content(client: IDotMatrixClient, t: timer.Timer, payload: bytes) -> bool:
    """Drives the sendData handshake manually: send one outer chunk, then wait
    for its TimerAck before sending the next one. Returns True once status=SAVED
    arrives for the final chunk, False on FAILED/timeout/unexpected status.
    """
    chunks = timer.build_timer_data_packets(t, payload)
    acks: asyncio.Queue = asyncio.Queue()
    unsubscribe = client.add_response_listener(
        lambda ack: acks.put_nowait(ack) if isinstance(ack, TimerAck) else None
    )
    try:
        for index, chunk in enumerate(chunks):
            is_last = index == len(chunks) - 1
            print(f"sending outer chunk {index + 1}/{len(chunks)} ({len(chunk)} BLE packets)...")
            await client._transport.write_packets([chunk], response=True)

            try:
                ack = await asyncio.wait_for(acks.get(), _CHUNK_ACK_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                print(
                    f"ABORT: no TimerAck arrived within {_CHUNK_ACK_TIMEOUT_SECONDS}s after "
                    f"chunk {index + 1}/{len(chunks)}. The chunked handshake may not use this "
                    "characteristic/format at all on this firmware -- record this."
                )
                return False

            if ack.status == TIMER_STATUS_FAILED:
                print(f"ABORT: device reported FAILED (status=0) after chunk {index + 1}.")
                return False
            if ack.status == TIMER_STATUS_SAVED:
                if not is_last:
                    print(
                        f"UNEXPECTED: device reported SAVED (status=3) after chunk {index + 1}/"
                        f"{len(chunks)}, before the final chunk. Record this -- either the doc's "
                        "chunking assumption is wrong, or SAVED can arrive early."
                    )
                print("Device reported SAVED (status=3).")
                return True
            if ack.status == TIMER_STATUS_NEXT_CHUNK:
                if is_last:
                    print(
                        "UNEXPECTED: device asked for NEXT_CHUNK (status=1) after what should "
                        "have been the final chunk. Record this."
                    )
                continue
            print(f"ABORT: unrecognized TimerAck status={ack.status}. Record the raw bytes above.")
            return False

        print("ABORT: ran out of chunks without ever seeing status=SAVED.")
        return False
    finally:
        unsubscribe()


async def main(mac: str | None, slot: int) -> None:
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, mac_address=mac)
    client.add_response_listener(_print_ack)  # attached before any send, per convention

    print("connecting...")
    await client.connect()
    try:
        fire_at = datetime.now() + timedelta(minutes=_FIRE_IN_MINUTES)
        t = timer.Timer(
            num=slot,
            week=0xFF,  # unpatched raw bitmask; guessed as "every day", unverified
            hour=fire_at.hour,
            minute=fire_at.minute,
            duration_bucket=timer.DURATION_30S,  # long enough to observe when it fires
            content_type=timer.CONTENT_GIF,  # hardware-confirmed: only CONTENT_GIF actually renders
            buzzer_enable=True,
        )
        payload = _build_test_gif(client.screen_size.width)
        print(
            f"\n--- uploading alarm content to slot {slot}, firing at "
            f"{fire_at.strftime('%H:%M')} (in ~{_FIRE_IN_MINUTES} min) ---"
        )
        saved = await _upload_timer_content(client, t, payload)
        if not saved:
            print("Upload did not complete; not waiting for fire time.")
            return

        print(
            f"\nUpload acknowledged as SAVED. Now wait until {fire_at.strftime('%H:%M')} "
            f"(~{_FIRE_IN_MINUTES} minutes from now) and watch the panel."
        )
        print(
            "VISUAL CHECK: at fire time, the panel shows the clock for a few seconds first "
            "(this is expected, not a bug) before the alarm's content takes over. Does the "
            "yellow/red checkerboard then animate (frames swapping) for approximately "
            f"{timer.DURATION_SECONDS[t.duration_bucket]} seconds? Does the buzzer sound "
            "(buzzer_enable=True was sent)? Does the panel revert to its prior content afterward?"
        )
        input("Press Enter once you've observed the fire event (or once well past fire time)...")

        print(f"\n--- closing (disabling) slot {slot} ---")
        await client.experimental.timer_close(t)
        print(
            "VISUAL CHECK: confirm the alarm no longer fires if you wait past its scheduled "
            "time again (it should now be disabled, not deleted)."
        )
    finally:
        await client.disconnect()
        print("disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", default=None, help="device MAC address; omit to auto-discover")
    parser.add_argument("--slot", type=int, default=0, help="timer slot to use, 0..9")
    args = parser.parse_args()
    asyncio.run(main(args.mac, args.slot))
