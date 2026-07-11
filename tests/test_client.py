"""Tests that IDotMatrixClient wires feature namespaces to one shared transport."""

from idotmatrix.client import IDotMatrixClient
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
