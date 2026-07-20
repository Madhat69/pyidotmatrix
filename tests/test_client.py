"""Tests that IDotMatrixClient wires feature namespaces to one shared transport."""

import asyncio

import pytest

from pyidotmatrix import client as client_module
from pyidotmatrix.client import ChunkedUploadError, IDotMatrixClient
from pyidotmatrix.exceptions import CommandRejectedError, UploadError
from pyidotmatrix.protocol import schedule, timer
from pyidotmatrix.protocol.response import (
    STATUS_FAILED,
    STATUS_NEXT_CHUNK,
    STATUS_SAVED,
    DeviceAck,
    StatusAck,
)
from pyidotmatrix.screen import ScreenSize


class FakeTransport:
    """Records what would be written, without any BLE."""

    def __init__(self):
        self.writes: list[tuple[bytes, bool]] = []
        self.packet_writes: list = []
        self.response_listeners: list = []
        self.is_connected = False
        # Commands routed through await_device_ack (the verified path), so a
        # test can tell a verified send from a fire-and-forget one -- both land
        # in `writes` as response=True writes, indistinguishable there.
        self.ack_waits: list[bytes] = []
        # What await_device_ack hands back to a verified _send. Default None
        # models the bounded-timeout "no ack arrived" case (no raise); a test
        # sets it to a DeviceAck to drive the accept/reject paths.
        self.next_ack = None

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    async def write(self, data, response=False):
        self.writes.append((bytes(data), response))

    async def write_packets(self, packets, response=False):
        self.packet_writes.append((packets, response))

    async def await_device_ack(self, command, timeout=2.0):
        # Mirrors the real transport: the verified write is recorded here (as a
        # response=True write) instead of via write(), so writes-assertions on
        # verified commands still hold. Returns the preset ack (or None).
        self.ack_waits.append(bytes(command))
        self.writes.append((bytes(command), True))
        return self.next_ack

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


# --- reject-raises-by-default: _send awaits the device ack (M2) --------------


def _device_ack(command_type: int, command_subtype: int, accepted: bool) -> DeviceAck:
    status = 0x01 if accepted else 0x00
    return DeviceAck(
        command_type=command_type,
        command_subtype=command_subtype,
        accepted=accepted,
        raw=bytes([0x05, 0x00, command_type, command_subtype, status]),
    )


async def test_send_raises_command_rejected_on_nack():
    client, transport = _client()
    transport.next_ack = _device_ack(7, 8, accepted=False)  # countdown's key
    with pytest.raises(CommandRejectedError) as excinfo:
        await client.countdown.start(25, 0)
    assert excinfo.value.ack.accepted is False
    assert excinfo.value.raw == bytes([0x05, 0x00, 7, 8, 0x00])  # carries the raw ack


async def test_send_does_not_raise_on_accept():
    client, transport = _client()
    transport.next_ack = _device_ack(7, 8, accepted=True)
    await client.countdown.start(25, 0)  # must not raise
    assert transport.writes == [(bytes([7, 0, 8, 128, 1, 25, 0]), True)]


async def test_send_does_not_raise_on_missing_ack():
    client, transport = _client()
    transport.next_ack = None  # bounded-timeout "no ack" case
    await client.common.set_brightness(50)  # must not raise


async def test_status_ack_saved_is_not_a_rejection():
    """The misparse that shipped three broken features: a StatusAck SAVED
    (status=3) must never be read as a nack. A verified _send whose command's
    ack is a StatusAck must not raise."""
    client, transport = _client()
    # Text upload (0x03, 0x00) is a StatusAck key; SAVED is a successful save.
    transport.next_ack = StatusAck(command_type=0x03, command_subtype=0x00, status=STATUS_SAVED, raw=b"\x05\x00\x03\x00\x03")
    await client.experimental.timer_close(_timer_obj())  # StatusAck path, must not raise


async def test_set_command_verification_false_suppresses_the_raise():
    client, transport = _client()
    client.set_command_verification(False)
    transport.next_ack = _device_ack(4, 128, accepted=False)  # would nack if awaited
    await client.common.set_brightness(50)  # fire-and-forget: must not raise
    # written directly (response via write(), not the await_device_ack path)
    assert transport.writes == [(bytes([5, 0, 4, 128, 50]), True)]


async def test_verify_commands_false_constructor_kwarg_suppresses_the_raise():
    transport = FakeTransport()
    transport.next_ack = _device_ack(4, 128, accepted=False)
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, transport=transport, verify_commands=False)
    await client.common.set_brightness(50)  # must not raise


async def test_verify_password_is_fire_and_forget():
    """verify_password must not open a pending (5, 2) ack wait -- that key
    collides with graffiti's nack (docs/APK_SECOND_PASS.md Q4)."""
    client, transport = _client()
    transport.next_ack = _device_ack(5, 2, accepted=False)  # a colliding graffiti-style nack
    await client.common.verify_password(123456)  # must not raise despite the nack
    assert transport.writes == [(bytes([7, 0, 5, 2, 12, 34, 56]), True)]
    assert transport.ack_waits == []  # never opened a pending (5, 2) ack wait


async def test_graffiti_send_skips_the_ack_wait():
    """Graffiti is genuinely ack-silent; a verified _send must write it directly
    rather than await_device_ack (which refuses graffiti)."""
    client, transport = _client()
    transport.next_ack = _device_ack(5, 2, accepted=False)  # ignored: graffiti never awaits
    await client.graffiti.set_pixels((0, 255, 0), [(1, 1)])  # must not raise
    assert transport.ack_waits == []  # graffiti wrote directly, never awaited an ack


# --- context manager + connect_to convenience (M2) --------------------------


async def test_async_context_manager_connects_and_disconnects():
    transport = FakeTransport()
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, transport=transport)
    async with client as entered:
        assert entered is client
        assert transport.is_connected  # connected on enter
    assert not transport.is_connected  # disconnected on exit


async def test_async_context_manager_disconnects_on_exception():
    transport = FakeTransport()
    client = IDotMatrixClient(ScreenSize.SIZE_32x32, transport=transport)
    with pytest.raises(RuntimeError):
        async with client:
            assert transport.is_connected
            raise RuntimeError("boom")
    assert not transport.is_connected  # exit ran despite the exception


async def test_connect_to_accepts_deviceinfo_and_defers_connect():
    from pyidotmatrix import DeviceInfo

    info = DeviceInfo(name="IDM-A03EAF", address="AA:BB:CC:DD:EE:01", rssi=-40)
    client = IDotMatrixClient.connect_to(info, ScreenSize.SIZE_32x32)
    assert client._transport._mac_address == "AA:BB:CC:DD:EE:01"
    assert not client.is_connected  # connect_to constructs; connect happens on __aenter__


async def test_connect_to_accepts_bare_address_string():
    client = IDotMatrixClient.connect_to("11:22:33:44:55:66", ScreenSize.SIZE_32x32)
    assert client._transport._mac_address == "11:22:33:44:55:66"
