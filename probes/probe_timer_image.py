"""Hardware probe: Timer sendData (chunked custom-image alarm upload).

EXPERIMENTAL: protocol/timer.py's build_timer_data_packets bytes come from
decompiled-APK research (docs/ALARM_BUZZER_APK_FINDINGS.md in the research lab),
never exercised against real hardware. This is the riskiest surface in the
Timer/Schedule subsystem: a multi-chunk upload whose ack vocabulary
(TimerAck: status 1 = send next chunk, 3 = fully saved, 0 = failed) is
unconfirmed, which is exactly why there is no client method for it yet (see
ExperimentalFeature.timer_close's docstring) -- only this probe drives the
handshake, by hand, one outer chunk at a time.

Sets a real alarm 2 minutes in the future on the given slot, with a small
generated checkerboard image as its content and the buzzer on, then tells the
human what to watch for at fire time.

Usage:
    python probes/probe_timer_image.py [--mac AA:BB:CC:DD:EE:FF] [--slot 0]

Not run in CI -- no hardware access exists in the dev environment this was
written in. A human runs this with a real panel in view and records what they
observe at each VISUAL CHECK line.
"""

import argparse
import asyncio
from datetime import datetime, timedelta

from PIL import Image

from idotmatrix.client import IDotMatrixClient
from idotmatrix.imaging import adapt_image
from idotmatrix.protocol import timer
from idotmatrix.protocol.response import TIMER_STATUS_FAILED, TIMER_STATUS_NEXT_CHUNK, TIMER_STATUS_SAVED, TimerAck
from idotmatrix.screen import ScreenSize

_CHUNK_ACK_TIMEOUT_SECONDS = 5.0
_FIRE_IN_MINUTES = 2


def _build_test_image(size: int) -> bytes:
    """A yellow/red checkerboard -- easy to recognize as the alarm's own content
    (distinct from whatever was on the panel before it fired). Reuses the
    driver's own imaging pipeline (adapt_image) so the payload is in the exact
    device-ready RGB format the DIY frame path already proves works, same as
    the doc's note that Timer's image payload has "the same layout" as a plain
    frame upload.
    """
    source = Image.new("RGB", (size, size))
    pixels = source.load()
    for y in range(size):
        for x in range(size):
            pixels[x, y] = (255, 255, 0) if (x // 4 + y // 4) % 2 == 0 else (200, 0, 0)
    return adapt_image(source, size, do_palettize=True)


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
            content_type=timer.CONTENT_IMAGE,
            buzzer_enable=True,
        )
        payload = _build_test_image(client.screen_size.width)
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
            "VISUAL CHECK: at fire time, does the panel show the yellow/red checkerboard "
            f"for approximately {timer.DURATION_SECONDS[t.duration_bucket]} seconds? Does the "
            "buzzer sound (buzzer_enable=True was sent)? Does the panel revert to its prior "
            "content afterward?"
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
