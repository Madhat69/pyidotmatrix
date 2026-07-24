"""BLE transport: owns the connection to one device and writes bytes to it.

Responsibilities:
  - connect (by MAC or discovery), disconnect, report connection state
  - write commands and multi-packet frames, chunked to the negotiated write size
  - keep the connection alive: reconnect supervision lives here, not in the app
  - surface device acks (fa03 notifications) and connection/observability events

It knows nothing about frames, deltas, scheduling, or scenes — it moves bytes.

Two distinct acknowledgements exist and must not be confused:
  - the GATT write response (`response=True` on a write) — a BLE-level confirmation
    that this device happens to withhold until it has processed the write;
  - the device ack (`DeviceAck` from fa03) — an application-level accept/reject the
    device pushes for each recognized command. Use await_device_ack() for the latter.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from bleak import AdvertisementData, BleakClient, BleakScanner
from bleak.exc import BleakError

from pyidotmatrix.exceptions import ConnectionLostError
from pyidotmatrix.protocol.response import DeviceAck, StatusAck, parse_response
from pyidotmatrix.transport.const import DEVICE_NAME_PREFIX, UUID_NOTIFY, UUID_WRITE
from pyidotmatrix.transport.status import TransportEvent, TransportEventKind, TransportSnapshot

logger = logging.getLogger(__name__)

# bleak caps write-with-response at 512 bytes.
_MAX_WRITE_WITH_RESPONSE = 512

# Some iDotMatrix panels on BlueZ report this tiny size but actually accept ~514.
# We no longer override automatically (that breaks genuinely low-MTU devices); we
# trust the reported size and hint the caller toward write_size_override.
_LIKELY_UNDERREPORT_SIZE = 20

# write_size_override sanity bounds. Floor: BLE's default ATT_MTU (23) minus the
# 3-byte ATT header leaves 20 usable payload bytes -- nothing smaller is a valid
# write size on any link. Ceiling: 517 is BLE's spec-maximum ATT_MTU, so 514
# (517 - 3) is the largest payload any real link can produce -- this is also the
# documented BlueZ-underreport escape-hatch value above, so the ceiling must
# clear it. A value outside this range is not a plausible write size; passing
# one silently (e.g. a negative override making the chunking loop's range()
# empty) drops every write with no error.
_MIN_WRITE_SIZE_OVERRIDE = 20
_MAX_WRITE_SIZE_OVERRIDE = 517

_RECONNECT_INTERVAL_SECONDS = 5
# M2 hardware hardening (DAEMON_PLAN.md's risk flag): adapter death (USB
# unplug, post-resume WinRT breakage) means every reconnect attempt is a
# discovery/connect round-trip against hardware that may simply be gone for a
# while. Retrying at a flat 5s forever would hammer a vanished adapter
# indefinitely; back off exponentially, capped, per failed attempt.
_RECONNECT_MAX_INTERVAL_SECONDS = 60
_DEFAULT_ACK_TIMEOUT = 2.0

# In every ported command, byte 2 is the type; only graffiti uses value 5 there,
# and graffiti produces no device ack — so we refuse to await one for it.
_GRAFFITI_TYPE_BYTE = 5

ConnectionCallback = Callable[[], Awaitable[None]]
ResponseCallback = Callable[[DeviceAck | StatusAck], None]
EventCallback = Callable[[TransportEvent], None]
Unsubscribe = Callable[[], None]


@dataclass(frozen=True)
class DeviceInfo:
    """A discovered iDotMatrix device: its advertised name, BLE address, and the
    advertisement RSSI if the backend reported one."""

    name: str
    address: str
    rssi: int | None = None


async def discover_devices(name_prefix: str = DEVICE_NAME_PREFIX) -> list[str]:
    """Returns the MAC addresses of nearby iDotMatrix devices."""
    found = await BleakScanner.discover(return_adv=True)
    addresses = []
    for device, adv in found.values():
        if isinstance(adv, AdvertisementData) and adv.local_name and adv.local_name.startswith(name_prefix):
            logger.info("found device %s (%s)", device.address, adv.local_name)
            addresses.append(device.address)
    return addresses


async def discover(name_prefix: str = DEVICE_NAME_PREFIX) -> list[DeviceInfo]:
    """Scans for nearby iDotMatrix devices, returning rich DeviceInfo records.

    A thin wrapper over BleakScanner.discover: no retries, no connection. Filters
    to devices whose advertised name starts with name_prefix ("IDM-"). Pass a
    DeviceInfo (or its .address) straight to IDotMatrixClient.connect_to.
    """
    found = await BleakScanner.discover(return_adv=True)
    devices = []
    for device, adv in found.values():
        if isinstance(adv, AdvertisementData) and adv.local_name and adv.local_name.startswith(name_prefix):
            devices.append(DeviceInfo(name=adv.local_name, address=device.address, rssi=adv.rssi))
    return devices


class BleTransport:
    def __init__(
        self,
        mac_address: str | None = None,
        auto_reconnect: bool = True,
        write_size_override: int | None = None,
    ):
        """
        Args:
            mac_address: device MAC, or None to connect to the first discovered device.
            auto_reconnect: if True, transparently reconnect after an unexpected drop.
            write_size_override: force the no-response write size instead of trusting
                the characteristic. Escape hatch for BlueZ panels that under-report
                (set to 514); leave None to use the reported size. Must be an int in
                [20, 517] (BLE's practical write-size range) -- raises ValueError
                otherwise, since e.g. a negative value silently empties the
                chunking loop and drops every write with no error.
        """
        if write_size_override is not None and not (
            isinstance(write_size_override, int)
            and _MIN_WRITE_SIZE_OVERRIDE <= write_size_override <= _MAX_WRITE_SIZE_OVERRIDE
        ):
            raise ValueError(
                f"write_size_override must be an int {_MIN_WRITE_SIZE_OVERRIDE}.."
                f"{_MAX_WRITE_SIZE_OVERRIDE}, got {write_size_override!r}"
            )
        self._mac_address = mac_address
        self._auto_reconnect = auto_reconnect      # configured intent
        self._reconnect_armed = False              # armed on connect, disarmed on explicit disconnect
        self._write_size_override = write_size_override
        self._client: BleakClient | None = None
        self._connect_lock = asyncio.Lock()        # per-instance: multiple devices don't serialize
        self._write_size: int | None = None     # negotiated no-response size, cached per connection
        self._reconnect_task: asyncio.Task | None = None
        # Serializes write()/write_packets() so one logical command's full
        # multi-packet send can't be interleaved with another writer's packets
        # on the wire (item 3, code review). Not held across connect()/
        # _reconnect_for_readiness() -- those take only _connect_lock, so a
        # write-triggered reconnect never tries to reacquire this lock and
        # can't deadlock against it (asyncio.Lock is not reentrant).
        self._write_lock = asyncio.Lock()

        self._on_connected: list[ConnectionCallback] = []
        self._on_disconnected: list[ConnectionCallback] = []
        self._on_response: list[ResponseCallback] = []
        self._on_event: list[EventCallback] = []
        # Keyed by (command_type, command_subtype), matched against incoming
        # acks in _handle_notification. KNOWN COLLISION (docs/APK_SECOND_PASS.md,
        # Q4): verify_password's expected ack key is (5, 2) -- build_verify_password
        # sends [7,0,5,2,...] -- and graffiti's hardware-observed rejection nack is
        # the byte-identical [5,0,5,2,0], i.e. the same (5, 2) key. A pending
        # verify_password wait could be resolved by an unrelated graffiti nack if
        # graffiti writes are interleaved with it. See await_device_ack's docstring
        # for the caller-facing guidance; this is documentation only, no dispatch
        # logic changed -- the vendor app itself has no stronger correlation (a
        # single-slot "last writer wins" callback, see Q4), so our (type,subtype)
        # keying is already an improvement, just not a complete one.
        self._pending_acks: dict[tuple[int, int], asyncio.Future] = {}

        self._reconnect_count = 0
        self._last_failure: str | None = None
        self._last_failure_at: float | None = None

    # --- connection lifecycle ---------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def is_write_ready(self) -> bool:
        """True if connected AND this connection's GATT services have actually
        been resolved.

        M2 reconnect drill finding: bleak's `is_connected` can be True while
        service discovery hasn't completed or populated for this session (a
        connect interrupted between session-establish and discovery, or
        certain post-resume/post-power-cycle WinRT states). Writing in that
        window doesn't fail here -- it fails one call later, deep inside
        bleak, when `write_gatt_char` touches the `services` property. Probe
        that property defensively instead: it raises BleakError when
        discovery hasn't happened, and we don't assume any bleak-internal
        alternative. An empty/missing collection also counts as not ready.
        """
        if not self.is_connected:
            return False
        assert self._client is not None  # is_connected just guaranteed it
        try:
            services = self._client.services
        except BleakError:
            return False
        return services is not None and any(True for _ in services)

    @property
    def auto_reconnect(self) -> bool:
        return self._auto_reconnect

    async def connect(self) -> None:
        """Connects to the device, discovering one first if no MAC was given."""
        async with self._connect_lock:
            if self.is_connected:
                return
            if self._mac_address is None:
                self._mac_address = await self._discover_one()

            logger.info("connecting to %s", self._mac_address)
            self._client = BleakClient(self._mac_address, disconnected_callback=self._handle_disconnect)
            await self._client.connect()
            self._write_size = None  # re-read from the new connection
            await self._subscribe_to_responses()
            self._reconnect_armed = self._auto_reconnect
            logger.info("connected to %s", self._mac_address)

        await self._notify_connection(self._on_connected)

    async def disconnect(self) -> None:
        """Disconnects and stops reconnect supervision until the next connect()."""
        self._reconnect_armed = False  # an explicit disconnect is not a candidate for reconnect
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        async with self._connect_lock:
            if self.is_connected:
                assert self._client is not None  # is_connected just guaranteed it
                await self._client.disconnect()

    def set_auto_reconnect(self, enabled: bool) -> None:
        """Enables or disables reconnect supervision at runtime.

        Enabling while connected arms supervision immediately; disabling disarms it
        and cancels any in-flight reconnect loop.
        """
        self._auto_reconnect = enabled
        if enabled:
            self._reconnect_armed = self.is_connected
        else:
            self._reconnect_armed = False
            if self._reconnect_task:
                self._reconnect_task.cancel()
                self._reconnect_task = None

    async def _discover_one(self) -> str:
        addresses = await discover_devices()
        if not addresses:
            raise BleakError(
                "no iDotMatrix devices found; ensure the device is powered on, in range, "
                "and not connected elsewhere"
            )
        return addresses[0]

    # --- writing -----------------------------------------------------------

    async def write(self, data: bytes | bytearray, response: bool = False) -> None:
        """Writes a single command, chunked to the write size. GATT-acks the last
        chunk if response=True.

        Holds _write_lock for the full send so this command's chunks can't be
        interleaved on the wire with another concurrent write()/write_packets()
        call (item 3, code review) -- without it, two logical commands writing
        at once could produce a byte stream the device reassembles as neither.
        """
        await self._ensure_connected()
        chunk_size = await self._resolve_write_size(response)
        async with self._write_lock:
            for start in range(0, len(data), chunk_size):
                is_last = start + chunk_size >= len(data)
                await self._write_raw(data[start:start + chunk_size], response=response and is_last)

    async def write_packets(self, packets: list[list[bytearray]], response: bool = False) -> None:
        """Writes a multi-chunk frame. Only the very last write is GATT-acked.

        Each element of packets is one protocol chunk already split into BLE-sized
        packets (see protocol.image.build_frame_packets). Builders split at the
        protocol's default size; if this connection negotiated a smaller write size,
        packets are re-split here — the device reassembles by the length header in
        each chunk, so BLE write boundaries don't matter to it.

        Holds _write_lock for the full send, same atomicity guarantee as write()
        (item 3, code review).
        """
        if not packets:
            return
        await self._ensure_connected()
        write_size = await self._resolve_write_size(response=False)
        async with self._write_lock:
            for chunk_index, chunk in enumerate(packets):
                is_last_chunk = chunk_index == len(packets) - 1
                for packet_index, packet in enumerate(chunk):
                    is_last_packet = packet_index == len(chunk) - 1
                    for start in range(0, len(packet), write_size):
                        piece = packet[start:start + write_size]
                        is_final = (
                            response and is_last_chunk and is_last_packet and start + write_size >= len(packet)
                        )
                        await self._write_raw(piece, response=is_final)

    async def await_device_ack(
        self, command: bytes | bytearray, timeout: float = _DEFAULT_ACK_TIMEOUT
    ) -> DeviceAck | StatusAck | None:
        """Sends a command and waits for the device's fa03 ack for it.

        Returns None if no ack arrived within timeout (the device stays silent
        for unrecognized commands). Otherwise returns whichever ack shape the
        command's (type, subtype) resolves to on the wire (see
        protocol/response.py's parse_response): a plain DeviceAck (boolean
        accepted/rejected) for ordinary commands, or a StatusAck (the 3-way
        NEXT_CHUNK/SAVED/FAILED vocabulary) for the status-ack family --
        currently Timer sendData/sendCloseData, Schedule's per-theme upload, and
        text upload (the exact (type, subtype) keys in
        protocol.response._STATUS_ACK_KEYS). Most one-shot config commands (the
        common callers of this method) only ever produce DeviceAck; StatusAck
        shows up here only if a caller manually awaits one of the chunked-upload
        commands instead of going through the client's _send_chunked_upload
        handshake. Correlated by the command's type/subtype bytes. Raises
        ValueError for graffiti (never acked) or if a wait is already pending
        for the same command type/subtype — the facade does not serialize, so
        two same-typed waits could not be told apart.

        CAVEAT (docs/APK_SECOND_PASS.md, Q4): this (type, subtype) correlation is
        stronger than the vendor app's own (a single mutable "last writer wins"
        callback slot with no content check), but has one known collision --
        verify_password's ack key is (5, 2), and a graffiti rejection nack is the
        byte-identical [5,0,5,2,0]. A pending await_device_ack(verify_password
        command) could be incorrectly resolved by a graffiti nack if graffiti
        writes are interleaved with it. Do not interleave graffiti writes with a
        pending verify_password wait.
        """
        if len(command) < 4:
            raise ValueError("command too short to correlate an ack")
        if command[2] == _GRAFFITI_TYPE_BYTE:
            raise ValueError("graffiti commands produce no device ack")
        key = (command[2], command[3])
        if key in self._pending_acks:
            raise ValueError(f"an ack wait is already pending for command type {key}")

        future = asyncio.get_running_loop().create_future()
        self._pending_acks[key] = future
        try:
            await self.write(command, response=True)
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            return None
        finally:
            self._pending_acks.pop(key, None)

    async def _ensure_connected(self) -> None:
        """The write-readiness gate for write() and write_packets().

        Not the same question as is_connected: a connected-but-not-ready
        client (see is_write_ready) would pass a plain is_connected check and
        then blow up on the very next write_gatt_char call. Force a clean
        reconnect in that case instead of writing into a client we already
        know will raise.
        """
        if not self.is_connected:
            await self.connect()
        elif not self.is_write_ready:
            logger.warning(
                "connected to %s but GATT services not resolved; forcing a clean reconnect",
                self._mac_address,
            )
            await self._reconnect_for_readiness()

    async def _reconnect_for_readiness(self) -> None:
        """Recovers from connected-but-not-write-ready by disconnecting the
        stale client, then reconnecting via the normal connect() flow (which
        builds a fresh BleakClient and re-subscribes to notifications).

        Deliberately calls the stale client's disconnect() directly rather
        than self.disconnect(): self.disconnect() disarms reconnect
        supervision and takes _connect_lock, and connect() below takes that
        same lock itself -- asyncio.Lock is not reentrant, so holding it
        across this call would deadlock. Going through the client directly
        keeps this a plain disconnect-then-reconnect with no lock held
        across the boundary, and leaves reconnect supervision's arm state to
        connect() as usual.
        """
        stale_client = self._client
        if stale_client is not None:
            try:
                await stale_client.disconnect()
            except Exception as ex:
                logger.warning("error disconnecting not-ready client: %s", ex)
        await self.connect()

    async def _write_raw(self, data: bytes | bytearray, response: bool, _retry_on_failure: bool = True) -> None:
        """Writes one chunk, with one self-healing retry on failure.

        M2 lid-close finding: after a host suspend/resume, bleak/WinRT can
        report a client as connected with services resolved (is_write_ready
        passes it) while the underlying session is dead -- the physical link
        came back, but this BleakClient object's session did not. That
        surfaces here, on the write itself (BleakError "Unreachable", or an
        OSError from a dead adapter) -- NOT as is_write_ready going False and
        NOT as bleak's disconnected_callback firing, so plain reconnect
        supervision (_reconnect_loop) never starts on its own. Left
        unhandled, every future write into this transport fails forever
        with no visible symptom besides silence -- worse than the crash it
        replaces, since the daemon looks alive.

        On a write failure, force a clean reconnect (_reconnect_for_readiness:
        disconnect the stale client, reconnect via connect(), which builds a
        fresh BleakClient) and retry this exact chunk once. If the device is
        genuinely gone (powered off, adapter vanished), _reconnect_for_readiness's
        own connect() call raises -- reconnection is exhausted at that point, so
        we raise ConnectionLostError chained from the underlying bleak error
        instead of letting it escape raw (item 7, code review); the caller does
        not get a second recovery path here, but the next write attempt's
        _ensure_connected (is_connected freshly False) will try connect() again
        on its own. If reconnect succeeds but the retried write also fails, that
        is also reconnection-exhausted (only one self-heal attempt per write) and
        raises the same ConnectionLostError, chained from that second failure --
        callers (Presenter et al.) are expected to catch it, log it, and let the
        next attempt try again.
        """
        assert self._client is not None  # callers hold a connected transport (_ensure_connected)
        try:
            await self._client.write_gatt_char(UUID_WRITE, data, response=response)
        except Exception as ex:
            self._record_failure(f"write failed: {ex}")
            self._emit_event(TransportEventKind.WRITE_FAILED, str(ex))
            if not _retry_on_failure:
                raise ConnectionLostError(
                    f"write to {self._mac_address} failed after a reconnect-and-retry: {ex}"
                ) from ex
            logger.warning(
                "write to %s failed on a client that looked write-ready (%s); "
                "forcing a clean reconnect and retrying once",
                self._mac_address, ex,
            )
            try:
                await self._reconnect_for_readiness()
            except Exception as reconnect_ex:
                raise ConnectionLostError(
                    f"write to {self._mac_address} failed and reconnect could not recover: {reconnect_ex}"
                ) from reconnect_ex
            await self._write_raw(data, response=response, _retry_on_failure=False)

    async def _resolve_write_size(self, response: bool) -> int:
        """The largest write we may send. Response writes are capped by bleak;
        no-response writes use the override, else the characteristic's reported size."""
        if response:
            return _MAX_WRITE_WITH_RESPONSE
        if self._write_size_override is not None:
            return self._write_size_override
        if self._write_size is None:
            assert self._client is not None  # only reachable on a connected transport
            char = self._client.services.get_characteristic(UUID_WRITE)
            assert char is not None  # UUID_WRITE resolved at connect time
            self._write_size = char.max_write_without_response_size
            if self._write_size <= _LIKELY_UNDERREPORT_SIZE:
                logger.info(
                    "device reports a %d-byte write size; if this is an iDotMatrix panel on "
                    "BlueZ, pass write_size_override=514 for full-speed frames",
                    self._write_size,
                )
        return self._write_size

    # --- observability -----------------------------------------------------

    def snapshot(self) -> TransportSnapshot:
        """A read-only view of the transport's current state."""
        return TransportSnapshot(
            address=self._mac_address,
            is_connected=self.is_connected,
            write_size=self._write_size_override or self._write_size,
            reconnect_count=self._reconnect_count,
            last_failure=self._last_failure,
            last_failure_at=self._last_failure_at,
        )

    def _record_failure(self, message: str) -> None:
        self._last_failure = message
        self._last_failure_at = time.time()

    def _emit_event(self, kind: TransportEventKind, detail: str | None = None) -> None:
        event = TransportEvent(kind=kind, detail=detail)
        for callback in list(self._on_event):
            _safe_call(callback, event)

    # --- listeners ---------------------------------------------------------

    def add_listener(
        self,
        on_connected: ConnectionCallback | None = None,
        on_disconnected: ConnectionCallback | None = None,
    ) -> Unsubscribe:
        """Registers async connection-state callbacks. Returns an unsubscribe callable."""
        if on_connected:
            self._on_connected.append(on_connected)
        if on_disconnected:
            self._on_disconnected.append(on_disconnected)

        def unsubscribe() -> None:
            _discard(self._on_connected, on_connected)
            _discard(self._on_disconnected, on_disconnected)

        return unsubscribe

    def add_response_listener(self, callback: ResponseCallback) -> Unsubscribe:
        """Registers a callback for device acks (accept/reject per command). Returns
        an unsubscribe callable. Only the BLE backend has these."""
        self._on_response.append(callback)
        return lambda: _discard(self._on_response, callback)

    def add_event_listener(self, callback: EventCallback) -> Unsubscribe:
        """Registers a callback for transport events (write failures, reconnects).
        Returns an unsubscribe callable."""
        self._on_event.append(callback)
        return lambda: _discard(self._on_event, callback)

    async def _subscribe_to_responses(self) -> None:
        """Subscribes to the notify characteristic so device acks are delivered.

        Best-effort: a stack that doesn't support notifications must not break the
        connection, since acks are observability, not a hard requirement.
        """
        assert self._client is not None  # called from connect() right after the client is built
        try:
            await self._client.start_notify(UUID_NOTIFY, self._handle_notification)
        except Exception as ex:
            logger.warning("could not subscribe to device notifications: %s", ex)

    def _handle_notification(self, _sender: object, data: bytearray) -> None:
        ack = parse_response(bytes(data))
        if ack is None:
            logger.debug("unrecognized notification: %s", bytes(data).hex())
            return
        # StatusAck (Timer sendData/sendCloseData, Schedule per-theme upload) has no
        # accepted/rejected concept -- it's a 3-way status (next-chunk / saved /
        # failed) instead of DeviceAck's boolean, so it never hits this warning even
        # when status != 0x01 (e.g. status=3 SAVED, a successful save).
        if isinstance(ack, DeviceAck) and not ack.accepted:
            logger.warning("device rejected command type=%d subtype=%d", ack.command_type, ack.command_subtype)

        # Keyed only by (type, subtype) -- see _pending_acks' definition for the
        # known (5, 2) verify_password/graffiti-nack collision caveat.
        pending = self._pending_acks.get((ack.command_type, ack.command_subtype))
        if pending and not pending.done():
            pending.set_result(ack)

        for callback in list(self._on_response):
            _safe_call(callback, ack)

    def _handle_disconnect(self, _client: BleakClient) -> None:
        """bleak disconnect callback (sync). Fans out and starts reconnecting."""
        logger.info("disconnected from %s", self._mac_address)
        asyncio.ensure_future(self._notify_connection(self._on_disconnected))
        if self._reconnect_armed and (self._reconnect_task is None or self._reconnect_task.done()):
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Retries connect() until it succeeds or supervision is disarmed.

        M2 adapter-death audit finding: connect() already builds a brand new
        BleakClient on every call (see connect() above) -- it never reuses a
        stale one, so a dead adapter (USB unplug, post-resume WinRT
        breakage) can't wedge this loop onto an unusable client object, and
        the broad except below already survives any BleakError connect()
        raises. What was missing, and is added here: (a) capped exponential
        backoff, so a genuinely vanished adapter isn't hammered every 5s
        forever, and (b) a per-attempt event so callers can observe each
        rebuild-and-retry, not just the start/end of the whole campaign.
        """
        self._emit_event(TransportEventKind.RECONNECT_STARTED)
        delay = _RECONNECT_INTERVAL_SECONDS
        while self._reconnect_armed and not self.is_connected:
            await asyncio.sleep(delay)
            if not self._reconnect_armed:
                # mypy narrows _reconnect_armed to True from the loop condition, but
                # disconnect()/set_auto_reconnect flip it concurrently across the await.
                break  # type: ignore[unreachable]
            self._emit_event(TransportEventKind.RECONNECT_ATTEMPT, f"rebuilding client (next backoff {delay}s)")
            try:
                await self.connect()
                self._reconnect_count += 1
                self._emit_event(TransportEventKind.RECONNECT_SUCCEEDED)
            except asyncio.CancelledError:
                break
            except Exception as ex:
                self._record_failure(f"reconnect failed: {ex}")
                logger.warning("reconnect attempt failed: %s", ex)
                delay = min(delay * 2, _RECONNECT_MAX_INTERVAL_SECONDS)

    async def _notify_connection(self, callbacks: list[ConnectionCallback]) -> None:
        for callback in list(callbacks):
            try:
                await callback()
            except Exception as ex:
                logger.warning("connection listener raised: %s", ex)


def _safe_call(callback: Callable, argument: object) -> None:
    """Invokes a sync listener, isolating its failure from connection handling."""
    try:
        callback(argument)
    except Exception as ex:
        logger.warning("listener raised: %s", ex)


def _discard(callbacks: list, callback: object) -> None:
    if callback in callbacks:
        callbacks.remove(callback)
