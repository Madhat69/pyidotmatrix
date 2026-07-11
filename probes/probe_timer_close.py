"""Hardware probe: Timer sendCloseData (disable an alarm slot without deleting it).

EXPERIMENTAL: protocol/timer.py's build_timer_close bytes come from decompiled-APK
research (docs/ALARM_BUZZER_APK_FINDINGS.md in the research lab), never exercised
against real hardware. This is the second-smallest surface in the Timer/Schedule
subsystem: a flat 12-byte packet, no chunking, no payload.

The doc flags two open questions this probe should help resolve:
  1. Timer's ack family may not fit the driver's existing DeviceAck shape at all
     (docs call it "[_, 0, 0, 0x80, status]" with a 1/3/0 status vocabulary,
     distinct from DeviceAck's plain accept/reject) -- protocol/response.py now
     parses this as a TimerAck, but whether *this specific* command (close, not
     the chunked upload) actually produces a reply on today's firmware is
     unconfirmed. This probe prints the raw ack either way.
  2. The close command's duration field endianness is unverified: the doc lists
     it as little-endian (dur_lo, dur_hi) here but big-endian in the chunked
     sendData header for the same logical field -- see build_timer_close's
     docstring. This probe can't test that directly (no payload to compare
     against), but a mismatch would likely show as the device silently
     rejecting/ignoring the command, worth noting if that happens.

Usage:
    python probes/probe_timer_close.py [--mac AA:BB:CC:DD:EE:FF] [--slot 0]

Not run in CI -- no hardware access exists in the dev environment this was
written in. A human runs this with a real device and records what they observe
at each VISUAL CHECK line.
"""

import argparse
import asyncio

from idotmatrix.client import IDotMatrixClient
from idotmatrix.protocol import timer
from idotmatrix.protocol.response import DeviceAck, TimerAck
from idotmatrix.screen import ScreenSize


def _print_raw(ack) -> None:
    """Prints whatever comes back, without assuming DeviceAck vs. TimerAck shape."""
    if isinstance(ack, TimerAck):
        print(
            f"[listener] TimerAck: command_type={ack.command_type} "
            f"command_subtype={ack.command_subtype} status={ack.status} raw={ack.raw.hex()}"
        )
    elif isinstance(ack, DeviceAck):
        print(
            f"[listener] DeviceAck: type={ack.command_type} subtype={ack.command_subtype} "
            f"accepted={ack.accepted} raw={ack.raw.hex()}"
        )
    else:
        print(f"[listener] unrecognized ack object: {ack!r}")


async def main(mac: str | None, slot: int) -> None:
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, mac_address=mac)
    client.add_response_listener(_print_raw)  # attached before any send, per convention

    print("connecting...")
    await client.connect()
    try:
        t = timer.Timer(
            num=slot,
            week=0,  # unpatched raw bitmask; day mapping unverified regardless
            hour=0,
            minute=0,
            duration_bucket=timer.DURATION_10S,
            content_type=timer.CONTENT_IMAGE,
            buzzer_enable=False,
        )
        command = timer.build_timer_close(t)
        print(f"\n--- timer_close(slot={slot}) ---")
        print(f"sending {command.hex()}...")

        # await_device_ack correlates on bytes 2-3 (0x00, 0x80), matching both the
        # TimerAck dispatch in response.py and this command's own header bytes.
        ack = await client.await_device_ack(command)
        if ack is None:
            print(
                "VISUAL CHECK: no fa03 reply arrived within the timeout. Record: does "
                "sendCloseData produce no ack at all on this firmware?"
            )
        else:
            _print_raw(ack)
            print(
                "VISUAL CHECK: record the exact shape above. If it's a TimerAck, note "
                "which status value (0/1/3) a close command actually returns -- the doc's "
                "1/3/0 vocabulary was derived from the chunked sendData path, not "
                "sendCloseData, so a close command might use a different status or none."
            )
        input("Press Enter to finish...")
    finally:
        await client.disconnect()
        print("disconnected.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac", default=None, help="device MAC address; omit to auto-discover")
    parser.add_argument("--slot", type=int, default=0, help="timer slot to close, 0..9")
    args = parser.parse_args()
    asyncio.run(main(args.mac, args.slot))
