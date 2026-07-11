"""Transport tests with a stubbed bleak client (no BLE hardware)."""

import asyncio

import pytest

from idotmatrix.protocol import common, graffiti
from idotmatrix.transport import ble
from idotmatrix.transport.ble import BleTransport
from idotmatrix.transport.status import TransportEventKind


class StubCharacteristic:
    def __init__(self, max_write: int):
        self.max_write_without_response_size = max_write


class StubServices:
    def __init__(self, max_write: int):
        self._char = StubCharacteristic(max_write)

    def get_characteristic(self, _uuid):
        return self._char


class StubBleakClient:
    """Stand-in for bleak.BleakClient. Reported write size comes from the module global."""

    reported_write_size = 514

    def __init__(self, address=None, disconnected_callback=None):
        self.is_connected = False
        self.writes: list[tuple[bytes, bool]] = []
        self.services = StubServices(type(self).reported_write_size)
        self.disconnected_callback = disconnected_callback
        self.notify_cb = None
        self.fail_writes = False

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    async def start_notify(self, _uuid, callback):
        self.notify_cb = callback

    async def write_gatt_char(self, _uuid, data, response=False):
        if self.fail_writes:
            raise RuntimeError("simulated write failure")
        self.writes.append((bytes(data), response))


def _install(monkeypatch, reported_write_size=514):
    StubBleakClient.reported_write_size = reported_write_size
    monkeypatch.setattr(ble, "BleakClient", StubBleakClient)


@pytest.fixture
def transport(monkeypatch) -> BleTransport:
    _install(monkeypatch)
    return BleTransport(mac_address="00:11:22:33:44:55")


# --- write sizing ---------------------------------------------------------

async def test_frame_resplit_when_characteristic_reports_low_mtu(monkeypatch):
    # The characteristic itself reports 20 bytes (not just the cache). With the
    # automatic 20->514 override removed, writes must honor the real 20-byte limit.
    _install(monkeypatch, reported_write_size=20)
    transport = BleTransport(mac_address="00:11:22:33:44:55")
    await transport.connect()

    packet = bytearray(range(256)) * 2  # one 512-byte protocol packet
    await transport.write_packets([[packet]], response=True)

    writes = transport._client.writes
    assert all(len(data) <= 20 for data, _ in writes)
    assert b"".join(data for data, _ in writes) == bytes(packet)  # nothing lost/reordered
    assert [r for _, r in writes] == [False] * (len(writes) - 1) + [True]  # only final write acked


async def test_write_size_override_forces_size(monkeypatch):
    _install(monkeypatch, reported_write_size=20)
    transport = BleTransport(mac_address="00:11:22:33:44:55", write_size_override=514)
    await transport.connect()
    await transport.write_packets([[bytearray(509)]], response=False)
    assert transport._client.writes == [(bytes(bytearray(509)), False)]


async def test_default_trusts_reported_size(transport):
    await transport.connect()
    await transport.write_packets([[bytearray(509)]], response=False)
    assert transport._client.writes == [(bytes(bytearray(509)), False)]


# --- reconnect lifecycle --------------------------------------------------

async def test_reconnect_rearms_after_manual_disconnect_and_reconnect(transport):
    await transport.connect()
    assert transport._reconnect_armed is True
    await transport.disconnect()
    assert transport._reconnect_armed is False
    await transport.connect()
    assert transport._reconnect_armed is True


async def test_auto_reconnect_disabled_never_arms(monkeypatch):
    _install(monkeypatch)
    transport = BleTransport(mac_address="00:11:22:33:44:55", auto_reconnect=False)
    await transport.connect()
    assert transport._reconnect_armed is False


async def test_set_auto_reconnect_arms_and_disarms(transport):
    await transport.connect()
    transport.set_auto_reconnect(False)
    assert transport._reconnect_armed is False and transport.auto_reconnect is False
    transport.set_auto_reconnect(True)
    assert transport._reconnect_armed is True and transport.auto_reconnect is True


async def test_unexpected_drop_triggers_reconnect(monkeypatch):
    monkeypatch.setattr(ble, "_RECONNECT_INTERVAL_SECONDS", 0.01)
    _install(monkeypatch)
    transport = BleTransport(mac_address="00:11:22:33:44:55")
    events = []
    transport.add_event_listener(events.append)
    await transport.connect()

    client = transport._client
    client.is_connected = False
    client.disconnected_callback(client)  # simulate an unexpected drop

    await asyncio.sleep(0.05)
    assert transport.is_connected
    assert transport._reconnect_count == 1
    assert any(e.kind == TransportEventKind.RECONNECT_SUCCEEDED for e in events)


# --- device ack correlation ----------------------------------------------

async def test_await_device_ack_correlates_by_type(transport):
    await transport.connect()
    command = common.build_set_brightness(50)  # type 4, subtype 128
    task = asyncio.create_task(transport.await_device_ack(command, timeout=1))
    await asyncio.sleep(0)  # let it register and write
    transport._client.notify_cb(None, bytearray.fromhex("0500048001"))  # accepted
    ack = await task
    assert ack is not None and ack.accepted


async def test_await_device_ack_times_out_to_none(transport):
    await transport.connect()
    ack = await transport.await_device_ack(common.build_set_brightness(50), timeout=0.05)
    assert ack is None


async def test_await_device_ack_rejects_graffiti(transport):
    await transport.connect()
    command = graffiti.build_set_pixels((1, 2, 3), [(0, 0)])
    with pytest.raises(ValueError):
        await transport.await_device_ack(command)


async def test_await_device_ack_rejects_duplicate_wait(transport):
    await transport.connect()
    command = common.build_set_brightness(50)
    task = asyncio.create_task(transport.await_device_ack(command, timeout=1))
    await asyncio.sleep(0)
    with pytest.raises(ValueError):
        await transport.await_device_ack(command)  # same type/subtype still pending
    transport._client.notify_cb(None, bytearray.fromhex("0500048001"))
    await task


# --- observability & isolation -------------------------------------------

async def test_write_failure_records_and_emits(transport):
    await transport.connect()
    transport._client.fail_writes = True
    events = []
    transport.add_event_listener(events.append)
    with pytest.raises(RuntimeError):
        await transport.write(common.build_set_brightness(50), response=True)
    assert any(e.kind == TransportEventKind.WRITE_FAILED for e in events)
    assert transport.snapshot().last_failure is not None


async def test_snapshot_reports_state(transport):
    await transport.connect()
    await transport.write(common.build_set_brightness(50))
    snap = transport.snapshot()
    assert snap.is_connected and snap.address == "00:11:22:33:44:55"
    assert snap.write_size == 514 and snap.reconnect_count == 0


async def test_listener_failure_is_isolated(transport):
    await transport.connect()
    seen = []
    transport.add_response_listener(lambda ack: (_ for _ in ()).throw(RuntimeError("boom")))
    transport.add_response_listener(seen.append)
    transport._client.notify_cb(None, bytearray.fromhex("0500048001"))  # must not raise
    assert len(seen) == 1  # second listener still ran


async def test_unsubscribe_removes_listener(transport):
    await transport.connect()
    seen = []
    unsubscribe = transport.add_response_listener(seen.append)
    unsubscribe()
    transport._client.notify_cb(None, bytearray.fromhex("0500048001"))
    assert seen == []
