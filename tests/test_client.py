"""Tests that IDotMatrixClient wires feature namespaces to one shared transport."""

import pytest

from idotmatrix.client import IDotMatrixClient
from idotmatrix.protocol import timer
from idotmatrix.screen import ScreenSize


class FakeTransport:
    """Records what would be written, without any BLE."""

    def __init__(self):
        self.writes: list[tuple[bytes, bool]] = []
        self.packet_writes: list = []
        self.response_listeners: list = []
        self.is_connected = False

    async def write(self, data, response=False):
        self.writes.append((bytes(data), response))

    async def write_packets(self, packets, response=False):
        self.packet_writes.append((packets, response))

    def add_listener(self, on_connected=None, on_disconnected=None):
        return lambda: None

    def add_response_listener(self, callback):
        self.response_listeners.append(callback)
        return lambda: self.response_listeners.remove(callback)


def _client() -> tuple[IDotMatrixClient, FakeTransport]:
    transport = FakeTransport()
    return IDotMatrixClient(ScreenSize.SIZE_32x32, transport=transport), transport


async def test_countdown_routes_to_transport_with_ack():
    client, transport = _client()
    await client.countdown.start(25, 0)
    assert transport.writes == [(bytes([7, 0, 8, 128, 1, 25, 0]), True)]


async def test_all_feature_namespaces_present():
    client, _ = _client()
    for name in (
        "chronograph", "countdown", "clock", "scoreboard", "eco",
        "color", "graffiti", "effect", "music_sync", "text", "gif", "common", "display",
        "experimental",
    ):
        assert hasattr(client, name), f"missing namespace: {name}"


async def test_graffiti_mirror_passes_through():
    client, transport = _client()
    await client.graffiti.set_pixels((0, 255, 0), [(1, 1)], mirror=3)
    (data, _ack), = transport.writes
    assert data[3] == 3  # mirror byte


async def test_response_listener_registers_with_transport():
    client, transport = _client()
    callback = lambda ack: None
    client.add_response_listener(callback)
    assert callback in transport.response_listeners


async def test_features_and_display_share_one_transport():
    client, transport = _client()
    await client.chronograph.start()
    await client.common.set_brightness(50)
    # both commands went through the same transport instance
    assert len(transport.writes) == 2
    assert client._transport is transport


async def test_reset_uses_packet_path():
    client, transport = _client()
    await client.common.reset()
    assert len(transport.packet_writes) == 1


async def test_verify_password_routes_to_transport():
    client, transport = _client()
    await client.common.verify_password(123456)
    assert transport.writes == [(bytes([7, 0, 5, 2, 12, 34, 56]), True)]


async def test_set_screen_timeout_routes_to_transport():
    client, transport = _client()
    await client.common.set_screen_timeout(30)
    assert transport.writes == [(bytes([5, 0, 15, 128, 30]), True)]


async def test_read_screen_timeout_routes_to_transport():
    client, transport = _client()
    await client.common.read_screen_timeout()
    assert transport.writes == [(bytes([5, 0, 15, 128, 255]), True)]


async def test_experimental_set_time_indicator_routes_to_transport():
    client, transport = _client()
    await client.experimental.set_time_indicator(True)
    assert transport.writes == [(bytes([5, 0, 7, 128, 1]), True)]


async def test_experimental_delete_device_data_requires_confirm():
    client, _ = _client()
    with pytest.raises(ValueError):
        await client.experimental.delete_device_data()


async def test_experimental_delete_device_data_routes_to_transport_when_confirmed():
    client, transport = _client()
    await client.experimental.delete_device_data(confirm=True)
    assert transport.writes == [
        (bytes([17, 0, 2, 1, 12, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]), True)
    ]


async def test_experimental_schedule_master_switch_routes_to_transport():
    client, transport = _client()
    await client.experimental.schedule_master_switch(enable=True, buzzer=True)
    assert transport.writes == [(bytes([5, 0, 7, 0x80, 0b11]), True)]


async def test_experimental_timer_close_routes_to_transport():
    client, transport = _client()
    t = timer.Timer(
        num=1, week=0, hour=6, minute=0,
        duration_bucket=timer.DURATION_10S, content_type=timer.CONTENT_IMAGE, buzzer_enable=False,
    )
    await client.experimental.timer_close(t)
    assert transport.writes == [(bytes([12, 0, 0x00, 0x80, 1, 0, 6, 0, 10, 0, 2, 0]), True)]
