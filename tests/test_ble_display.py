"""BleDisplay tests with a fake transport (no BLE), covering the frame path
that was previously only exercised on hardware."""

import pytest

from pyidotmatrix.display.ble_display import BleDisplay
from pyidotmatrix.protocol import image
from pyidotmatrix.screen import ScreenSize


class FakeTransport:
    def __init__(self):
        self.writes: list[tuple[bytes, bool]] = []
        self.packet_writes: list = []
        self._on_disconnected = None

    async def write(self, data, response=False):
        self.writes.append((bytes(data), response))

    async def write_packets(self, packets, response=False):
        self.packet_writes.append((packets, response))

    def add_listener(self, on_connected=None, on_disconnected=None):
        if on_disconnected is not None:
            self._on_disconnected = on_disconnected
        return lambda: None

    async def simulate_disconnect(self):
        """Test helper: fires the on_disconnected callback BleDisplay registered,
        the same way a real BleTransport would after a dropped link."""
        await self._on_disconnected()


def _display():
    transport = FakeTransport()
    return BleDisplay(ScreenSize.SIZE_32x32, transport), transport


async def test_show_frame_enables_diy_mode_first_then_sends_packets():
    display, transport = _display()
    await display.show_frame(bytes(32 * 32 * 3))
    # first write is the DIY set-mode command (with response), then the frame packets.
    # O-27 (DAEMON_PLAN.md): default entry is clear=True (mode 1) -- with no
    # embedder telling the driver otherwise, the panel's prior state is unknown.
    assert transport.writes == [(bytes(image.build_set_diy_mode(mode=image.ENTER_CLEAR_CUR_SHOW)), True)]
    assert len(transport.packet_writes) == 1
    assert transport.packet_writes[0][1] is True  # frame acked by default


async def test_show_frame_entry_clear_false_uses_mode_3():
    # O-27: the embedder (daemon) opts into the flash-free entry once it knows
    # the panel is in a mode-3-safe state.
    display, transport = _display()
    display.set_entry_clear(False)
    await display.show_frame(bytes(32 * 32 * 3))
    assert transport.writes == [(bytes(image.build_set_diy_mode(mode=image.ENTER_NO_CLEAR_CUR_SHOW)), True)]


async def test_diy_mode_enabled_only_once():
    display, transport = _display()
    await display.show_frame(bytes(32 * 32 * 3))
    await display.show_frame(bytes(32 * 32 * 3))
    assert len(transport.writes) == 1  # set-mode sent once, not per frame


async def test_entry_clear_survives_reconnect_but_diy_mode_enabled_does_not():
    # The driver's own per-connection _diy_mode_enabled resets on reconnect
    # (that's what makes re-entry happen at all) -- but _entry_clear reflects
    # the embedder's policy, not device state, and must not be clobbered by a
    # disconnect. O-27's daemon-side re-entry (mode 3) relies on this.
    display, transport = _display()
    display.set_entry_clear(False)
    await display.show_frame(bytes(32 * 32 * 3))
    assert transport.writes[-1] == (bytes(image.build_set_diy_mode(mode=image.ENTER_NO_CLEAR_CUR_SHOW)), True)

    await transport.simulate_disconnect()
    await display.show_frame(bytes(32 * 32 * 3))
    # Still mode 3 -- set_entry_clear(False) was never re-called, and the
    # driver doesn't reset it on its own.
    assert transport.writes[-1] == (bytes(image.build_set_diy_mode(mode=image.ENTER_NO_CLEAR_CUR_SHOW)), True)
    assert len(transport.writes) == 2  # re-entered (diy_mode_enabled did reset)


async def test_show_frame_rejects_wrong_size():
    display, _ = _display()
    with pytest.raises(ValueError):
        await display.show_frame(bytes(10))


async def test_set_pixels_rejects_off_screen_coordinate():
    display, _ = _display()
    with pytest.raises(ValueError):
        await display.set_pixels((255, 0, 0), [(32, 0)])


async def test_invalidate_diy_mode_forces_reentry_on_next_frame():
    """A native takeover (text/clock/effect) exits DIY with NO disconnect, so
    the embedder must invalidate to make the next frame re-enter (hardware
    2026-07-20: without this, the reclaim frame after a text takeover was
    silently swallowed -- flag said in-DIY, no entry sent, full frames into
    text mode are dropped)."""
    display, transport = _display()
    await display.show_frame(bytes(32 * 32 * 3))
    await display.show_frame(bytes(32 * 32 * 3))
    assert len(transport.writes) == 1  # entered once, no re-entry while flagged in-DIY

    display.invalidate_diy_mode()
    await display.show_frame(bytes(32 * 32 * 3))
    assert len(transport.writes) == 2  # re-entered
    assert transport.writes[-1] == (bytes(image.build_set_diy_mode(mode=image.ENTER_CLEAR_CUR_SHOW)), True)
