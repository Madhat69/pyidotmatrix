import asyncio

from pyidotmatrix import IDotMatrixClient, ScreenSize


async def main():
    async with IDotMatrixClient.connect_to("6D:FD:F8:A0:3E:AF", ScreenSize.SIZE_32x32) as client:
        await client.common.reset()
        print("device reset sent", flush=True)
        await asyncio.sleep(5)

asyncio.run(main())
