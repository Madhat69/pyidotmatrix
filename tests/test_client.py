"""Tests that IDotMatrixClient wires feature namespaces to one shared transport."""

import asyncio

import pytest

from idotmatrix import client as client_module
from idotmatrix.client import ChunkedUploadError, IDotMatrixClient
from idotmatrix.protocol import schedule, timer
from idotmatrix.protocol.response import STATUS_FAILED, STATUS_NEXT_CHUNK, STATUS_SAVED, StatusAck
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


# --- experimental.timer_set / schedule_set_theme: chunked-upload handshake --
#
# FakeTransport's write_packets/add_response_listener let the test drive the
# StatusAck handshake by hand: create the upload as a background task, yield
# control so it writes the next outer chunk and starts waiting, then invoke
# the registered listener directly to simulate the device's fa03 ack.


def _status_ack(ack_type: int, ack_subtype: int, status: int) -> StatusAck:
    return StatusAck(
        command_type=ack_type,
        command_subtype=ack_subtype,
        status=status,
        raw=bytes([0x05, 0x00, ack_type, ack_subtype, status]),
    )


def _push_ack(transport: FakeTransport, ack: StatusAck) -> None:
    for callback in list(transport.response_listeners):
        callback(ack)


async def _yield_control(times: int = 3) -> None:
    """Runs enough event-loop turns for the upload task to reach its next
    suspension point (waiting on the ack queue), regardless of how many
    internal awaits asyncio.wait_for needs to get there."""
    for _ in range(times):
        await asyncio.sleep(0)


def _timer_obj(**overrides) -> timer.Timer:
    base = dict(
        num=0, week=0xFF, hour=0, minute=0,
        duration_bucket=timer.DURATION_10S, content_type=timer.CONTENT_GIF, buzzer_enable=False,
    )
    base.update(overrides)
    return timer.Timer(**base)


def _theme_obj(**overrides) -> schedule.ScheduleTheme:
    base = dict(index=0, week=0xFF, start_hour=0, start_min=0, end_hour=1, end_min=0)
    base.update(overrides)
    return schedule.ScheduleTheme(**base)


async def test_timer_set_single_chunk_goes_straight_to_saved():
    client, transport = _client()
    payload = b"x" * 10  # well under 4096: a single outer chunk
    task = asyncio.create_task(client.experimental.timer_set(_timer_obj(), payload))
    await _yield_control()

    _push_ack(transport, _status_ack(0x00, 0x80, STATUS_SAVED))
    await task

    assert len(transport.packet_writes) == 1


async def test_timer_set_multi_chunk_next_chunk_then_saved():
    client, transport = _client()
    payload = b"y" * 8200  # 4096 + 4096 + 8 -> three outer chunks
    task = asyncio.create_task(client.experimental.timer_set(_timer_obj(), payload))

    for _ in range(2):
        await _yield_control()
        _push_ack(transport, _status_ack(0x00, 0x80, STATUS_NEXT_CHUNK))
    await _yield_control()
    _push_ack(transport, _status_ack(0x00, 0x80, STATUS_SAVED))
    await task

    assert len(transport.packet_writes) == 3


async def test_timer_set_tolerates_duplicate_acks():
    client, transport = _client()
    payload = b"z" * 4200  # two outer chunks
    task = asyncio.create_task(client.experimental.timer_set(_timer_obj(), payload))

    await _yield_control()  # first chunk written, waiting for its ack
    # the real ack for chunk 1, plus a duplicate that arrives before chunk 2 is sent
    _push_ack(transport, _status_ack(0x00, 0x80, STATUS_NEXT_CHUNK))
    _push_ack(transport, _status_ack(0x00, 0x80, STATUS_NEXT_CHUNK))
    await _yield_control()  # duplicate is drained; chunk 2 is written; waiting again

    _push_ack(transport, _status_ack(0x00, 0x80, STATUS_SAVED))
    await task

    assert len(transport.packet_writes) == 2  # the duplicate did not cause a phantom third write


async def test_timer_set_failed_raises():
    client, transport = _client()
    task = asyncio.create_task(client.experimental.timer_set(_timer_obj(), b"a" * 5))
    await _yield_control()

    _push_ack(transport, _status_ack(0x00, 0x80, STATUS_FAILED))
    with pytest.raises(ChunkedUploadError):
        await task


async def test_timer_set_timeout_raises(monkeypatch):
    monkeypatch.setattr(client_module, "_CHUNK_ACK_TIMEOUT_SECONDS", 0.05)
    client, _ = _client()
    with pytest.raises(ChunkedUploadError):
        await client.experimental.timer_set(_timer_obj(), b"a" * 5)


async def test_schedule_set_theme_single_chunk_goes_straight_to_saved():
    client, transport = _client()
    payload = b"x" * 10
    task = asyncio.create_task(
        client.experimental.schedule_set_theme(_theme_obj(), payload, schedule.CONTENT_GIF)
    )
    await _yield_control()

    _push_ack(transport, _status_ack(0x05, 0x80, STATUS_SAVED))
    await task

    assert len(transport.packet_writes) == 1


async def test_schedule_set_theme_multi_chunk_next_chunk_then_saved():
    client, transport = _client()
    payload = b"y" * 8200  # three outer chunks
    task = asyncio.create_task(
        client.experimental.schedule_set_theme(_theme_obj(), payload, schedule.CONTENT_GIF)
    )

    for _ in range(2):
        await _yield_control()
        _push_ack(transport, _status_ack(0x05, 0x80, STATUS_NEXT_CHUNK))
    await _yield_control()
    _push_ack(transport, _status_ack(0x05, 0x80, STATUS_SAVED))
    await task

    assert len(transport.packet_writes) == 3


async def test_schedule_set_theme_tolerates_duplicate_acks():
    client, transport = _client()
    payload = b"z" * 4200  # two outer chunks
    task = asyncio.create_task(
        client.experimental.schedule_set_theme(_theme_obj(), payload, schedule.CONTENT_GIF)
    )

    await _yield_control()
    _push_ack(transport, _status_ack(0x05, 0x80, STATUS_NEXT_CHUNK))
    _push_ack(transport, _status_ack(0x05, 0x80, STATUS_NEXT_CHUNK))
    await _yield_control()

    _push_ack(transport, _status_ack(0x05, 0x80, STATUS_SAVED))
    await task

    assert len(transport.packet_writes) == 2


async def test_schedule_set_theme_failed_raises():
    client, transport = _client()
    task = asyncio.create_task(
        client.experimental.schedule_set_theme(_theme_obj(), b"a" * 5, schedule.CONTENT_GIF)
    )
    await _yield_control()

    _push_ack(transport, _status_ack(0x05, 0x80, STATUS_FAILED))
    with pytest.raises(ChunkedUploadError):
        await task


async def test_schedule_set_theme_timeout_raises(monkeypatch):
    monkeypatch.setattr(client_module, "_CHUNK_ACK_TIMEOUT_SECONDS", 0.05)
    client, _ = _client()
    with pytest.raises(ChunkedUploadError):
        await client.experimental.schedule_set_theme(_theme_obj(), b"a" * 5, schedule.CONTENT_GIF)
