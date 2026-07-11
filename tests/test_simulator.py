"""Tests for SimulatorDisplay and DisplayBackend conformance of both backends."""

import pytest

from idotmatrix.display import DisplayBackend, SimulatorDisplay
from idotmatrix.display.ble_display import BleDisplay
from idotmatrix.screen import ScreenSize


def _make_sim(**kwargs) -> SimulatorDisplay:
    return SimulatorDisplay(ScreenSize.SIZE_32x32, **kwargs)


def test_backends_satisfy_protocol():
    assert isinstance(_make_sim(), DisplayBackend)
    # BleDisplay needs no live connection just to satisfy the interface check.
    from unittest.mock import MagicMock
    assert isinstance(BleDisplay(ScreenSize.SIZE_32x32, MagicMock()), DisplayBackend)


async def test_show_frame_replaces_framebuffer():
    sim = _make_sim()
    await sim.connect()
    frame = bytes([1, 2, 3]) * (32 * 32)
    await sim.show_frame(frame)
    assert sim.framebuffer == frame


async def test_show_frame_wrong_size_rejected():
    sim = _make_sim()
    with pytest.raises(ValueError):
        await sim.show_frame(bytes(10))


async def test_set_pixels_mutates_only_targeted_pixels():
    sim = _make_sim()
    await sim.connect()
    await sim.set_pixels((255, 0, 0), [(0, 0), (1, 0)])
    assert sim.framebuffer[0:3] == bytes([255, 0, 0])   # (0,0)
    assert sim.framebuffer[3:6] == bytes([255, 0, 0])   # (1,0)
    assert sim.framebuffer[6:9] == bytes([0, 0, 0])     # untouched


async def test_set_pixels_rejects_out_of_range_coordinates():
    sim = _make_sim()
    await sim.connect()
    for bad in [(0, 32), (32, 0), (-1, 0), (0, -1)]:
        with pytest.raises(ValueError):
            await sim.set_pixels((255, 0, 0), [bad])
    # framebuffer must be untouched and not grown
    assert len(sim.framebuffer) == 32 * 32 * 3
    assert sim.framebuffer == bytes(32 * 32 * 3)


async def test_set_pixels_addresses_by_row_major_xy():
    sim = _make_sim()
    await sim.connect()
    await sim.set_pixels((9, 9, 9), [(3, 2)])  # offset = (2*32 + 3) * 3
    offset = (2 * 32 + 3) * 3
    assert sim.framebuffer[offset:offset + 3] == bytes([9, 9, 9])


async def test_on_frame_callback_fires_on_changes():
    frames = []
    sim = _make_sim(on_frame=frames.append)
    await sim.connect()
    await sim.show_frame(bytes(32 * 32 * 3))
    await sim.set_pixels((1, 1, 1), [(0, 0)])
    assert len(frames) == 2


async def test_brightness_is_tracked_and_validated():
    sim = _make_sim()
    await sim.connect()
    await sim.set_brightness(70)
    assert sim.brightness == 70
    with pytest.raises(ValueError):
        await sim.set_brightness(200)


async def test_power_is_tracked():
    sim = _make_sim()
    await sim.connect()
    assert sim.power is True
    await sim.set_power(False)
    assert sim.power is False


async def test_frames_still_accepted_and_emitted_while_powered_off():
    frames = []
    sim = _make_sim(on_frame=frames.append)
    await sim.connect()
    await sim.set_power(False)
    await sim.show_frame(bytes([7, 7, 7]) * (32 * 32))
    assert frames  # callback fired despite power off
    assert sim.framebuffer[0:3] == bytes([7, 7, 7])  # framebuffer still updated


async def test_connection_listeners_fire():
    events = []

    async def on_up():
        events.append("up")

    async def on_down():
        events.append("down")

    sim = _make_sim()
    sim.add_listener(on_connected=on_up, on_disconnected=on_down)
    await sim.connect()
    await sim.disconnect()
    assert events == ["up", "down"]
