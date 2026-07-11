"""BleDisplay tests with a fake transport (no BLE), covering the frame path
that was previously only exercised on hardware."""

import pytest

from idotmatrix.display.ble_display import BleDisplay
from idotmatrix.protocol import image
from idotmatrix.screen import ScreenSize


class FakeTransport:
    def __init__(self):
        self.writes: list[tuple[bytes, bool]] = []
        self.packet_writes: list = []

    async def write(self, data, response=False):
        self.writes.append((bytes(data), response))

    async def write_packets(self, packets, response=False):
        self.packet_writes.append((packets, response))

    def add_listener(self, on_connected=None, on_disconnected=None):
        return lambda: None


def _display():
    transport = FakeTransport()
    return BleDisplay(ScreenSize.SIZE_32x32, transport), transport


async def test_show_frame_enables_diy_mode_first_then_sends_packets():
    display, transport = _display()
    await display.show_frame(bytes(32 * 32 * 3))
    # first write is the DIY set-mode command (with response), then the frame packets
    assert transport.writes == [(bytes(image.build_set_diy_mode(True)), True)]
    assert len(transport.packet_writes) == 1
    assert transport.packet_writes[0][1] is True  # frame acked by default


async def test_diy_mode_enabled_only_once():
    display, transport = _display()
    await display.show_frame(bytes(32 * 32 * 3))
    await display.show_frame(bytes(32 * 32 * 3))
    assert len(transport.writes) == 1  # set-mode sent once, not per frame


async def test_show_frame_rejects_wrong_size():
    display, _ = _display()
    with pytest.raises(ValueError):
        await display.show_frame(bytes(10))


async def test_set_pixels_rejects_off_screen_coordinate():
    display, _ = _display()
    with pytest.raises(ValueError):
        await display.set_pixels((255, 0, 0), [(32, 0)])
