"""Uploads a GIF for native on-device playback, handles a failed upload, and
demonstrates the ~1s instant re-show of a GIF the device already holds.

What this shows:
    - client.gif.upload_bytes() -- chunked upload paced on the device's ack
      handshake, catching UploadError (the device rejected a chunk, or the
      transfer never confirmed saved -- see docs/protocol-notes.md)
    - client.gif.activate_stored() -- if the device still holds the exact
      bytes you just uploaded, this switches playback back to them in ~1s
      via single-slot CRC recognition, with NO re-upload

Hardware needed: one iDotMatrix panel and a GIF file.

    python examples/05_gif_upload.py AA:BB:CC:DD:EE:FF nyan.gif
"""

import asyncio
import sys

from pyidotmatrix import DeviceInfo, IDotMatrixClient, ScreenSize, UploadError, discover
from pyidotmatrix.protocol import gif as gif_protocol


async def resolve_device(arg: str) -> DeviceInfo | str:
    if arg:
        return arg
    devices = await discover()
    if not devices:
        raise SystemExit("No iDotMatrix panel found and no address given.")
    return devices[0]


async def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(f"usage: python {sys.argv[0]} <address-or-empty> <gif-path>")
    device = await resolve_device(sys.argv[1])
    gif_path = sys.argv[2]

    async with IDotMatrixClient.connect_to(device, ScreenSize.SIZE_32x32) as client:
        # Adapt once and keep the resulting bytes: client.gif.upload_file()
        # would do this internally, but activate_stored() later needs the
        # literal bytes that ended up on the device, so we adapt ourselves
        # and reuse the same bytes for both calls.
        print(f"adapting {gif_path} to the {client.screen_size.width}x"
              f"{client.screen_size.height} canvas ...")
        gif_data = gif_protocol.adapt_gif(gif_path, canvas_size=client.screen_size.width)

        print("uploading ...")
        try:
            await client.gif.upload_bytes(gif_data)
        except UploadError as ex:
            # Chunked upload has a known chunk-2 race on some panels; the SDK
            # already retries the whole transfer once internally before
            # raising, so an UploadError here means both attempts failed.
            print(f"upload failed: {ex}")
            print(f"raw ack bytes: {ex.raw.hex() if ex.raw else '(none -- timeout)'}")
            return
        print("upload confirmed (device replied SAVED) -- GIF is playing.")
        await asyncio.sleep(4)

        # Switch away to something else, so the re-show below is visible.
        print("showing the clock to interrupt playback ...")
        await client.clock.show()
        await asyncio.sleep(3)

        # activate_stored sends only the first chunk and reads its ack: if the
        # device's single-slot CRC recognizes it as the currently-stored GIF,
        # it switches playback back in ~1s with no re-upload. Returns False
        # (not an error) if the device no longer holds these exact bytes --
        # e.g. something else was uploaded in between.
        print("reactivating the stored GIF via activate_stored() ...")
        switched = await client.gif.activate_stored(gif_data)
        if switched:
            print("switched back in ~1s, no re-upload needed.")
        else:
            print("device no longer holds these bytes; would need a fresh upload_bytes() call.")
        await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
