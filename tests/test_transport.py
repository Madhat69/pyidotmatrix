"""Transport tests with a stubbed bleak client (no BLE hardware)."""

import asyncio

import pytest
from bleak import AdvertisementData
from bleak.exc import BleakError

from pyidotmatrix.exceptions import ConnectionLostError
from pyidotmatrix.protocol import common, graffiti
from pyidotmatrix.protocol.response import STATUS_SAVED, StatusAck
from pyidotmatrix.transport import ble
from pyidotmatrix.transport.ble import BleTransport, DeviceInfo, discover
from pyidotmatrix.transport.status import TransportEventKind


class StubCharacteristic:
    def __init__(self, max_write: int):
        self.max_write_without_response_size = max_write


class StubServices:
    """Stand-in for bleak's BleakGATTServiceCollection, which is iterable over
    resolved services -- is_write_ready relies on that iteration to detect an
    empty/unresolved collection, so the stub mirrors it with one fake service."""

    def __init__(self, max_write: int):
        self._char = StubCharacteristic(max_write)

    def get_characteristic(self, _uuid):
        return self._char

    def __iter__(self):
        return iter([object()])  # one resolved "service"


class StubBleakClient:
    """Stand-in for bleak.BleakClient. Reported write size comes from the module global.

    connect_failures_remaining is a class attribute (not per-instance) because
    BleTransport.connect() builds a brand new StubBleakClient on every call --
    simulating an adapter that stays unreachable for N reconnect attempts
    requires the failure count to survive across those fresh instances.
    """

    reported_write_size = 514
    connect_failures_remaining = 0
    # M2 lid-close finding: a write can fail on a client that looked fully
    # ready (is_connected True, services resolved) -- a stale post-resume
    # WinRT session. Class attribute (not per-instance) for the same reason
    # as connect_failures_remaining: _write_raw's self-heal rebuilds a brand
    # new StubBleakClient via connect(), so a failure meant to survive that
    # rebuild (simulating a genuinely-gone device, not just a stale session)
    # must not reset just because the object changed.
    write_failures_remaining = 0

    def __init__(self, address=None, disconnected_callback=None):
        self.is_connected = False
        self.writes: list[tuple[bytes, bool]] = []
        self._services = StubServices(type(self).reported_write_size)
        # M2 drill: real bleak's `services` property raises BleakError until
        # discovery has completed for this connection, even if is_connected
        # is already True (see BleTransport.is_write_ready). Default True so
        # every existing test -- which never touches this flag -- keeps
        # seeing a ready client.
        self.services_ready = True
        self.disconnected_callback = disconnected_callback
        self.notify_cb = None
        self.fail_writes = False

    @property
    def services(self):
        if not self.services_ready:
            raise BleakError("Service Discovery has not been performed yet")
        return self._services

    async def connect(self):
        if type(self).connect_failures_remaining > 0:
            type(self).connect_failures_remaining -= 1
            raise BleakError("simulated adapter unreachable")
        self.is_connected = True
        self.services_ready = True  # a fresh connect() always re-discovers

    async def disconnect(self):
        self.is_connected = False

    async def start_notify(self, _uuid, callback):
        self.notify_cb = callback

    async def write_gatt_char(self, _uuid, data, response=False):
        if type(self).write_failures_remaining > 0:
            type(self).write_failures_remaining -= 1
            raise BleakError("simulated write failure (stale connected client)")
        if self.fail_writes:
            raise RuntimeError("simulated write failure")
        # A real GATT write always has to cross into the OS/radio stack, which
        # is a genuine suspension point. Yielding here (rather than completing
        # synchronously) lets two concurrently-running write()/write_packets()
        # calls actually interleave at the event-loop level if nothing is
        # serializing them -- needed for test_concurrent_write_packets_do_not_
        # interleave (item 3, code review) to be a meaningful test rather than
        # one where cooperative scheduling happens to run one call to
        # completion before the other starts regardless of any lock.
        await asyncio.sleep(0)
        self.writes.append((bytes(data), response))


def _install(monkeypatch, reported_write_size=514):
    StubBleakClient.reported_write_size = reported_write_size
    StubBleakClient.connect_failures_remaining = 0  # reset: class attr persists across tests
    StubBleakClient.write_failures_remaining = 0  # reset: class attr persists across tests
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


# --- write_size_override validation (item 2, code review) -----------------
#
# An unvalidated write_size_override let a negative value make the chunking
# loop's range() empty -- write()/write_packets() would then silently send
# nothing at all, with no error. Construction must reject anything outside a
# plausible BLE write-size range instead.

@pytest.mark.parametrize("bad_value", [-1, -514, 0, 19, 518, 10_000])
def test_write_size_override_rejects_out_of_range(bad_value):
    with pytest.raises(ValueError):
        BleTransport(mac_address="00:11:22:33:44:55", write_size_override=bad_value)


@pytest.mark.parametrize("good_value", [20, 514, 517])
def test_write_size_override_accepts_boundary_values(good_value):
    # Must not raise, including at the documented BlueZ-underreport escape
    # hatch (514) and both ends of the accepted range.
    BleTransport(mac_address="00:11:22:33:44:55", write_size_override=good_value)


def test_write_size_override_none_is_always_allowed():
    BleTransport(mac_address="00:11:22:33:44:55", write_size_override=None)


# --- write atomicity under concurrency (item 3, code review) ---------------
#
# Without serialization, two concurrent write_packets() calls could interleave
# their chunks on the wire -- the device would reassemble neither command
# correctly. StubBleakClient.write_gatt_char yields control on every write
# (see its comment above), so without a lock the two calls below would race
# and their bytes would land mixed together.

async def test_concurrent_write_packets_do_not_interleave(transport):
    await transport.connect()
    # Each element of the single outer chunk is already one BLE-sized packet,
    # so each produces its own _write_raw call -- three interleaving
    # opportunities per command, tagged by first byte so order is checkable.
    packets_a = [[bytearray([0xAA, i]) for i in range(3)]]
    packets_b = [[bytearray([0xBB, i]) for i in range(3)]]

    await asyncio.gather(
        transport.write_packets(packets_a, response=False),
        transport.write_packets(packets_b, response=False),
    )

    tags = [data[0] for data, _ in transport._client.writes]
    assert len(tags) == 6
    # One command's three writes must land as a contiguous block -- not mixed
    # with the other's -- regardless of which call happened to go first.
    assert tags == [0xAA, 0xAA, 0xAA, 0xBB, 0xBB, 0xBB] or tags == [0xBB, 0xBB, 0xBB, 0xAA, 0xAA, 0xAA]


async def test_concurrent_write_and_write_packets_do_not_interleave(transport):
    await transport.connect()
    # write() chunks a flat command by write size; force a tiny effective
    # chunk size via write_size_override so a modest payload still splits into
    # multiple _write_raw calls, same interleaving opportunity as above.
    transport._write_size_override = 20
    flat_command = bytes([0xCC]) * 60  # -> 3 chunks at 20 bytes each
    packets_d = [[bytearray([0xDD, i]) for i in range(3)]]

    await asyncio.gather(
        transport.write(flat_command, response=False),
        transport.write_packets(packets_d, response=False),
    )

    tags = [data[0] for data, _ in transport._client.writes]
    assert len(tags) == 6
    assert tags == [0xCC, 0xCC, 0xCC, 0xDD, 0xDD, 0xDD] or tags == [0xDD, 0xDD, 0xDD, 0xCC, 0xCC, 0xCC]


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


async def test_adapter_death_survives_bleak_errors_and_rebuilds_a_fresh_client(monkeypatch):
    """M2 audit: a vanished adapter (USB unplug / post-resume WinRT death)
    means every connect() attempt during reconnect raises BleakError for a
    while. The loop must not die, and must never retry against the same
    (now presumably broken) BleakClient object -- each attempt gets a fresh
    one via connect()'s existing `self._client = BleakClient(...)` rebuild.
    """
    monkeypatch.setattr(ble, "_RECONNECT_INTERVAL_SECONDS", 0.01)
    _install(monkeypatch)
    transport = BleTransport(mac_address="00:11:22:33:44:55")
    await transport.connect()
    first_client = transport._client

    StubBleakClient.connect_failures_remaining = 2  # "adapter gone" for the first 2 attempts
    first_client.is_connected = False
    first_client.disconnected_callback(first_client)

    await asyncio.sleep(0.2)
    assert transport.is_connected
    assert transport._reconnect_count == 1
    assert transport._client is not first_client  # never reused the dead object


async def test_reconnect_attempt_event_fires_per_attempt_with_capped_backoff(monkeypatch):
    monkeypatch.setattr(ble, "_RECONNECT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(ble, "_RECONNECT_MAX_INTERVAL_SECONDS", 0.03)
    _install(monkeypatch)
    transport = BleTransport(mac_address="00:11:22:33:44:55")
    events = []
    transport.add_event_listener(events.append)
    await transport.connect()

    StubBleakClient.connect_failures_remaining = 3
    client = transport._client
    client.is_connected = False
    client.disconnected_callback(client)

    await asyncio.sleep(0.3)
    assert transport.is_connected

    attempts = [e for e in events if e.kind == TransportEventKind.RECONNECT_ATTEMPT]
    assert len(attempts) == 4  # 3 failed rebuild-and-retry attempts + 1 that succeeded
    # backoff doubled after each failure, then capped at _RECONNECT_MAX_INTERVAL_SECONDS
    assert "0.01" in attempts[0].detail
    assert "0.02" in attempts[1].detail
    assert "0.03" in attempts[2].detail
    assert "0.03" in attempts[3].detail  # stayed capped, did not keep growing


async def test_reconnect_backoff_resets_on_a_fresh_drop_after_recovering(monkeypatch):
    monkeypatch.setattr(ble, "_RECONNECT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(ble, "_RECONNECT_MAX_INTERVAL_SECONDS", 0.05)
    _install(monkeypatch)
    transport = BleTransport(mac_address="00:11:22:33:44:55")
    events = []
    transport.add_event_listener(events.append)
    await transport.connect()

    # First drop: two failures before recovering, so backoff grows past base.
    StubBleakClient.connect_failures_remaining = 2
    client = transport._client
    client.is_connected = False
    client.disconnected_callback(client)
    await asyncio.sleep(0.2)
    assert transport.is_connected

    events.clear()
    # Second, independent drop: backoff must start over at the base interval,
    # not continue from wherever the previous campaign capped out.
    client = transport._client
    client.is_connected = False
    client.disconnected_callback(client)
    await asyncio.sleep(0.05)
    assert transport.is_connected

    attempts = [e for e in events if e.kind == TransportEventKind.RECONNECT_ATTEMPT]
    assert len(attempts) == 1
    assert "0.01" in attempts[0].detail


# --- write readiness (M2 drill: connected but services not resolved) -----
#
# Observed on real hardware: after a power-cycle/reconnect, bleak's
# is_connected can be True while GATT service discovery hasn't completed for
# the new session. The next write_gatt_char then raises deep inside bleak's
# `.services` property. is_write_ready / _ensure_connected must catch this
# and force a clean reconnect instead of writing into a client that will
# raise.

async def test_write_reconnects_when_connected_but_services_not_ready(transport):
    await transport.connect()
    stale_client = transport._client
    stale_client.services_ready = False  # discovery didn't complete this time
    assert transport.is_connected  # is_connected alone would say "fine"
    assert not transport.is_write_ready

    await asyncio.wait_for(transport.write(common.build_set_brightness(50)), timeout=1)

    assert stale_client.is_connected is False  # the stale client was disconnected
    assert transport._client is not stale_client  # connect() rebuilt a fresh one
    assert transport._client.writes  # and the write landed on the new client


async def test_write_packets_reconnects_when_connected_but_services_not_ready(transport):
    await transport.connect()
    stale_client = transport._client
    stale_client.services_ready = False

    packet = bytearray(range(256)) * 2
    await asyncio.wait_for(transport.write_packets([[packet]], response=True), timeout=1)

    assert transport._client is not stale_client
    assert b"".join(data for data, _ in transport._client.writes) == bytes(packet)


async def test_write_happy_path_does_not_reconnect(transport):
    await transport.connect()
    ready_client = transport._client

    await transport.write(common.build_set_brightness(50))

    assert transport._client is ready_client  # no reconnect triggered
    assert len(ready_client.writes) == 1  # exactly one write for one packet


async def test_write_connects_first_when_not_yet_connected(transport):
    assert not transport.is_connected
    await transport.write(common.build_set_brightness(50))
    assert transport.is_connected
    assert transport._client.writes


# --- write self-heal on a stale-but-ready client (M2 lid-close finding) ---
#
# Observed on real hardware: after a host suspend/resume, bleak/WinRT can
# report is_connected=True with services resolved -- is_write_ready passes it
# -- while the underlying session is actually dead. The write itself is what
# fails (BleakError "Unreachable"), not is_connected or is_write_ready, and
# bleak's disconnected_callback never fires for it, so plain reconnect
# supervision never starts on its own. _write_raw must force a reconnect and
# retry once instead of just propagating the first failure.

async def test_write_reconnects_and_retries_once_after_a_stale_client_write_failure(transport):
    await transport.connect()
    stale_client = transport._client
    assert transport.is_connected and transport.is_write_ready  # looked perfectly healthy

    StubBleakClient.write_failures_remaining = 1  # only the first attempt fails
    await asyncio.wait_for(transport.write(common.build_set_brightness(50)), timeout=1)

    assert stale_client.is_connected is False  # the stale client was disconnected
    assert transport._client is not stale_client  # connect() rebuilt a fresh one
    assert transport._client.writes  # and the retried write landed on the new client


async def test_write_raises_when_the_retry_also_fails(transport):
    """Models a genuinely-gone device (not just a stale session): even the
    fresh post-reconnect client can't write, so the caller must still see
    the failure -- only one self-heal attempt is made, not an unbounded loop.

    Reconnection is exhausted at that point (item 7, code review): the caller
    sees a driver-level ConnectionLostError, chained from the underlying
    bleak error, instead of a raw BleakError escaping the transport.
    """
    await transport.connect()
    StubBleakClient.write_failures_remaining = 999  # persists across the rebuilt client too
    events = []
    transport.add_event_listener(events.append)

    with pytest.raises(ConnectionLostError) as excinfo:
        await asyncio.wait_for(transport.write(common.build_set_brightness(50)), timeout=1)
    assert isinstance(excinfo.value.__cause__, BleakError)  # original error preserved via chaining

    write_failed_events = [e for e in events if e.kind == TransportEventKind.WRITE_FAILED]
    assert len(write_failed_events) == 2  # the original attempt and the one retry, both recorded


async def test_write_raises_connection_lost_when_reconnect_itself_fails(monkeypatch):
    """A different exhaustion path from the test above: the write fails, and
    the self-heal reconnect's own connect() call also fails (device genuinely
    gone). That must also surface as ConnectionLostError, not a raw BleakError
    from connect().
    """
    _install(monkeypatch)
    transport = BleTransport(mac_address="00:11:22:33:44:55")
    await transport.connect()
    StubBleakClient.write_failures_remaining = 1  # the first write attempt fails...
    StubBleakClient.connect_failures_remaining = 99  # ...and every reconnect attempt fails too

    with pytest.raises(ConnectionLostError) as excinfo:
        await asyncio.wait_for(transport.write(common.build_set_brightness(50)), timeout=1)
    assert isinstance(excinfo.value.__cause__, BleakError)


# --- discovery ------------------------------------------------------------


class _StubDevice:
    def __init__(self, address: str):
        self.address = address


def _adv(local_name, rssi=-52) -> AdvertisementData:
    return AdvertisementData(
        local_name=local_name, manufacturer_data={}, service_data={},
        service_uuids=[], tx_power=None, rssi=rssi, platform_data=(),
    )


def _install_scanner(monkeypatch, found: dict) -> None:
    class StubScanner:
        @staticmethod
        async def discover(return_adv=False):
            return found

    monkeypatch.setattr(ble, "BleakScanner", StubScanner)


async def test_discover_returns_deviceinfo_for_idm_devices(monkeypatch):
    found = {
        "AA:BB:CC:DD:EE:01": (_StubDevice("AA:BB:CC:DD:EE:01"), _adv("IDM-A03EAF", rssi=-40)),
        "AA:BB:CC:DD:EE:02": (_StubDevice("AA:BB:CC:DD:EE:02"), _adv("SomeOtherThing", rssi=-70)),
    }
    _install_scanner(monkeypatch, found)

    devices = await discover()

    assert devices == [DeviceInfo(name="IDM-A03EAF", address="AA:BB:CC:DD:EE:01", rssi=-40)]


async def test_discover_returns_empty_when_none_match(monkeypatch):
    _install_scanner(monkeypatch, {"X": (_StubDevice("X"), _adv("NotADisplay"))})
    assert await discover() == []


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


async def test_await_device_ack_returns_status_ack_for_status_family_commands(transport):
    """await_device_ack resolves to a StatusAck (not DeviceAck) for the
    chunked-upload status-ack family -- e.g. Timer sendData's (0x00, 0x80) key
    (item 10, code review: the prior `DeviceAck | None` return annotation was
    untruthful about this case)."""
    await transport.connect()
    command = bytearray([4, 0, 0x00, 0x80])  # Timer sendData's (type, subtype) key
    task = asyncio.create_task(transport.await_device_ack(command, timeout=1))
    await asyncio.sleep(0)
    transport._client.notify_cb(None, bytearray.fromhex("0500008003"))  # (0,0x80) status=3 SAVED
    ack = await task
    assert isinstance(ack, StatusAck)
    assert ack.status == STATUS_SAVED


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
    """A single failure is still recorded/emitted even though _write_raw's
    self-heal retry (see the stale-client tests above) recovers it and the
    overall write() call does not raise."""
    await transport.connect()
    StubBleakClient.write_failures_remaining = 1  # one failure, then reconnect+retry succeeds
    events = []
    transport.add_event_listener(events.append)
    await asyncio.wait_for(transport.write(common.build_set_brightness(50), response=True), timeout=1)
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
