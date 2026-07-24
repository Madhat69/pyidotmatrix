"""IDotMatrixClient: the full-feature facade over one device connection.

Groups every native device capability into namespaces (client.clock, client.countdown,
...) that share a single BleTransport with the frame-pipeline backend (client.display).
A caller can render frames through `display` and command native modes through the
feature namespaces over the same connection.

Config commands are written with response=True: the GATT write acknowledgement is
the device's flow-control signal, so no inter-command sleeps are needed.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from os import PathLike
from types import TracebackType
from typing import Any

from PIL import Image

from pyidotmatrix.display.backend import validate_coordinates
from pyidotmatrix.display.ble_display import BleDisplay
from pyidotmatrix.exceptions import CommandRejectedError, UploadError
from pyidotmatrix.imaging import ResizeMode, adapt_image
from pyidotmatrix.protocol import (
    chronograph,
    clock,
    common,
    countdown,
    eco,
    effect,
    fullscreen_color,
    gif,
    graffiti,
    music_sync,
    schedule,
    scoreboard,
    text,
    timer,
)
from pyidotmatrix.protocol.response import STATUS_NEXT_CHUNK, STATUS_SAVED, DeviceAck, StatusAck
from pyidotmatrix.screen import ScreenSize
from pyidotmatrix.transport.ble import _GRAFFITI_TYPE_BYTE, BleTransport, ConnectionCallback, DeviceInfo
from pyidotmatrix.transport.status import TransportEvent, TransportSnapshot

Color = tuple[int, int, int]

# How long to wait for a StatusAck after sending one outer chunk of a Timer/
# Schedule chunked upload. HARDWARE-CONFIRMED 2026-07-12: a real device replies
# within well under this on a 32x32 panel; 5s leaves headroom for BLE jitter.
_CHUNK_ACK_TIMEOUT_SECONDS = 5.0


# Back-compat alias: this driver raised ChunkedUploadError before the unified
# exception hierarchy (exceptions.py) existed. The name stays importable; it is
# now UploadError, so `except ChunkedUploadError` and `except UploadError` are
# the same catch, and both sit under IDotMatrixError.
ChunkedUploadError = UploadError


async def _send_chunked_upload(
    transport: BleTransport,
    chunks: list[list[bytearray]],
    ack_type: int,
    ack_subtype: int,
    label: str,
) -> None:
    """Drives the hardware-proven chunked-upload handshake (Timer sendData,
    Schedule per-theme upload): send one outer chunk, wait for its StatusAck,
    repeat.

    Uses a temporary response listener feeding an asyncio.Queue rather than
    transport.await_device_ack. await_device_ack correlates by (type, subtype)
    through a single pending Future per key, and raises if a second wait for
    the same key starts before the first resolves -- that fits one-shot config
    commands, but not this handshake: one call here needs to consume a whole
    *sequence* of same-keyed acks (one per chunk), plus tolerate a duplicate
    that's still in flight when the next chunk is sent. A Queue naturally
    buffers that sequence, including duplicates (which the loop below drains),
    and await_device_ack also only knows how to send a single flat command via
    transport.write -- it doesn't fit the multi-packet write_packets call each
    chunk needs. The listener is unsubscribed in `finally` so it never leaks
    past this call.

    NEXT_CHUNK -> send the next outer chunk. SAVED -> return (tolerates a
    single-chunk upload skipping NEXT_CHUNK and going straight to SAVED,
    hardware-confirmed 2026-07-12). FAILED, or any status this driver doesn't
    recognize -> raise UploadError carrying the raw ack. Timeout waiting for an
    ack -> raise UploadError. Sending every chunk without ever seeing a
    terminal SAVED (e.g. the device only ever answers NEXT_CHUNK) -> raise
    UploadError -- a transfer that never confirms SAVED must not read as a
    silent success (code review item 4: the previous "anything but FAILED
    means continue" logic let exactly this happen).

    Duplicate StatusAck frames (hardware sends them -- the same status
    observed twice for one chunk) are tolerated by draining any ack still
    sitting in the queue from the previous chunk before sending the next one.
    """
    acks: asyncio.Queue = asyncio.Queue()

    def _on_ack(ack: DeviceAck | StatusAck) -> None:
        if isinstance(ack, StatusAck) and ack.command_type == ack_type and ack.command_subtype == ack_subtype:
            acks.put_nowait(ack)

    unsubscribe = transport.add_response_listener(_on_ack)
    try:
        for index, chunk in enumerate(chunks):
            _drain_stale_acks(acks)  # discard a duplicate left over from the previous chunk
            await transport.write_packets([chunk], response=True)
            try:
                ack = await asyncio.wait_for(acks.get(), _CHUNK_ACK_TIMEOUT_SECONDS)
            except TimeoutError as ex:
                raise UploadError(
                    f"{label} upload: no ack within {_CHUNK_ACK_TIMEOUT_SECONDS}s after "
                    f"chunk {index + 1}/{len(chunks)}"
                ) from ex

            if ack.status == STATUS_SAVED:
                return  # early SAVED is expected for single-chunk uploads; tolerate it any time
            if ack.status == STATUS_NEXT_CHUNK:
                continue  # proceed to the next chunk
            # STATUS_FAILED or any status this driver doesn't recognize: never
            # treated as "keep going" -- raise, carrying the raw ack.
            raise UploadError(
                f"{label} upload rejected (status={ack.status}) at chunk {index + 1}/{len(chunks)}",
                raw=ack.raw,
            )
        # Every chunk was sent and every ack was NEXT_CHUNK, but no terminal
        # SAVED ever arrived -- the transfer did not confirm success.
        raise UploadError(f"{label} upload: sent all {len(chunks)} chunk(s) but never received a SAVED ack")
    finally:
        unsubscribe()


def _drain_stale_acks(acks: "asyncio.Queue") -> None:
    """Discards any ack already queued, without blocking. Used to shed a
    duplicate StatusAck (hardware sends them) before it's mistaken for the
    ack of the chunk about to be sent."""
    while not acks.empty():
        acks.get_nowait()


class _Feature:
    """Base for feature namespaces: holds the transport and sends built commands."""

    # Whether _send awaits the device ack and raises on a nack (see _send). The
    # client toggles this across all features via set_command_verification; a
    # single _send call can still override it explicitly (verify=...).
    _verify_commands = True

    def __init__(self, transport: BleTransport):
        self._transport = transport

    async def _send(self, data: bytearray, verify: bool | None = None) -> None:
        """Sends one flat command. By default awaits the device's fa03 ack and
        raises CommandRejectedError if the device nacks it.

        verify=None follows this feature's _verify_commands default (which the
        client's set_command_verification / verify_commands kwarg controls, the
        caller-facing fire-and-forget escape hatch). verify=True/False overrides
        it for this one call -- used internally to force fire-and-forget on the
        two paths that must never open a pending ack wait (graffiti, which is
        ack-silent, and verify_password, whose (5, 2) key collides with a
        graffiti nack).

        A StatusAck (Timer/Schedule/text upload family) is NEVER a rejection: a
        SAVED (status=3) reply is a success, and reading it as a nack is the
        misparse that shipped three broken features (see protocol/response.py).
        Only a boolean DeviceAck with accepted=False raises here.

        Correlation and silence are delegated to transport.await_device_ack: it
        registers the pending wait before writing (no race), and returns None on
        its bounded timeout, so a command that unexpectedly stays silent falls
        through rather than hanging. Graffiti (type byte 5) is genuinely
        ack-silent and await_device_ack refuses it, so any verified send skips
        the await for it and writes directly.
        """
        should_verify = self._verify_commands if verify is None else verify
        if not should_verify or len(data) < 4 or data[2] == _GRAFFITI_TYPE_BYTE:
            await self._transport.write(data, response=True)
            return
        ack = await self._transport.await_device_ack(data)
        if isinstance(ack, DeviceAck) and not ack.accepted:
            raise CommandRejectedError(ack)

    async def _send_packets(self, packets: list[list[bytearray]]) -> None:
        await self._transport.write_packets(packets, response=True)


class ChronographFeature(_Feature):
    """Stopwatch that counts up. Runs on the device once started."""

    async def reset(self) -> None:
        await self._send(chronograph.build_set_mode(chronograph.MODE_RESET))

    async def start(self) -> None:
        await self._send(chronograph.build_set_mode(chronograph.MODE_START))

    async def pause(self) -> None:
        await self._send(chronograph.build_set_mode(chronograph.MODE_PAUSE))

    async def resume(self) -> None:
        await self._send(chronograph.build_set_mode(chronograph.MODE_RESUME))


class CountdownFeature(_Feature):
    """Timer that counts down. A Pomodoro is countdown.start(25, 0)."""

    async def start(self, minutes: int, seconds: int = 0) -> None:
        await self._send(countdown.build_set_mode(countdown.MODE_START, minutes, seconds))

    async def stop(self) -> None:
        await self._send(countdown.build_set_mode(countdown.MODE_DISABLE, 0, 0))

    async def pause(self) -> None:
        await self._send(countdown.build_set_mode(countdown.MODE_PAUSE, 0, 0))

    async def restart(self) -> None:
        await self._send(countdown.build_set_mode(countdown.MODE_RESTART, 0, 0))


class ClockFeature(_Feature):
    async def show(
        self,
        style: int = clock.STYLE_RGB_SWIPE_OUTLINE,
        show_date: bool = True,
        hour24: bool = True,
        color: Color = (255, 255, 255),
    ) -> None:
        await self._send(clock.build_show(style, show_date, hour24, color))


class ScoreboardFeature(_Feature):
    async def show(self, count1: int, count2: int) -> None:
        await self._send(scoreboard.build_show(count1, count2))


class EcoFeature(_Feature):
    async def set_mode(
        self,
        enabled: bool = True,
        start_hour: int = 22,
        start_minute: int = 0,
        end_hour: int = 6,
        end_minute: int = 0,
        eco_brightness: int = 10,
    ) -> None:
        await self._send(
            eco.build_set_mode(enabled, start_hour, start_minute, end_hour, end_minute, eco_brightness)
        )


class FullscreenColorFeature(_Feature):
    async def show(self, color: Color) -> None:
        await self._send(fullscreen_color.build_show_color(color))


class GraffitiFeature(_Feature):
    """Draws pixels over the current framebuffer, with optional mirroring.

    The frame pipeline uses display.set_pixels (move_type off) for deltas;
    this namespace exists for graffiti drawing that wants the mirror modes
    (move_type MOVE_HORIZONTAL_MIRROR / MOVE_VERTICAL_MIRROR draws the pixels
    plus a mirrored copy -- hardware-mapped 2026-07-21, see protocol.graffiti).
    """

    def __init__(self, transport: BleTransport, screen_size: ScreenSize):
        super().__init__(transport)
        self._screen_size = screen_size

    async def set_pixels(
        self,
        color: Color,
        xys: list[tuple[int, int]],
        move_type: int = graffiti.MOVE_NONE,
    ) -> None:
        """Sets every coordinate in xys to color, batched to the device's
        per-command pixel limit.

        Validates every coordinate against this client's ScreenSize before
        anything goes on the wire (item 9, code review) -- unlike
        display.backend's set_pixels, this namespace previously had no size
        awareness of its own and would happily send off-screen coordinates.
        """
        validate_coordinates(xys, self._screen_size.width, self._screen_size.height)
        for start in range(0, len(xys), graffiti.MAX_PIXELS_PER_COMMAND):
            batch = xys[start:start + graffiti.MAX_PIXELS_PER_COMMAND]
            await self._send(graffiti.build_set_pixels(color, batch, move_type))


class EffectFeature(_Feature):
    """Built-in multi-color lighting effects (7 styles, 2..7 colors)."""

    async def show(self, style: int, colors: list[Color], speed: int = effect.SPEED_DEFAULT) -> None:
        """Activates an effect as a single flat command.

        speed is the real per-effect speed byte from the vendor app
        (docs/reverse-engineering/APK_SECOND_PASS.md Q5(a)); the default 90 is
        the historical hardcoded value this SDK has always sent. ⚠ speed
        values other than 90 are SOURCE-DERIVED, unverified on hardware.
        """
        await self._send(effect.build_show(style, colors, speed))

    async def show_chunked(
        self,
        style: int,
        colors: list[Color],
        speed: int = effect.SPEED_DEFAULT,
        mtu_negotiated: bool = True,
    ) -> None:
        """Activates an effect using the vendor app's own chunked framing.

        ⚠ SOURCE-DERIVED, unverified on hardware -- see
        protocol.effect.build_show_packets. show() is the hardware-proven path
        on 32x32; this exists for firmware that may expect the app's bespoke
        [chunkLen+1, chunkIndex]-framed transmission.
        """
        await self._send_packets([effect.build_show_packets(style, colors, speed, mtu_negotiated)])


class MusicSyncFeature(_Feature):
    async def set_mic_type(self, mic_type: int) -> None:
        await self._send(music_sync.build_set_mic_type(mic_type))

    async def send_image_rhythm(self, value: int) -> None:
        await self._send(music_sync.build_send_image_rhythm(value))

    async def stop_rhythm(self) -> None:
        await self._send(music_sync.build_stop_rhythm())


class TextFeature(_Feature):
    """Device-rendered scrolling text.

    Picks the wire format by screen size: 32x32 panels NACK the legacy/generic
    builder (probe 2026-07-19) and need build_text_packet_32x32 instead -- see
    protocol/text.py for the byte-level derivation. Other sizes -- and callers
    that construct this namespace directly without a screen_size, as
    glanceosd's BleTakeoverPort does -- keep using the generic builder pending
    their own per-size ports.
    """

    def __init__(self, transport: BleTransport, screen_size: ScreenSize | None = None):
        super().__init__(transport)
        self._screen_size = screen_size

    async def show(
        self,
        text_value: str,
        font_path: str,
        font_size: int = 16,
        text_mode: int = text.MODE_MARQUEE,
        speed: int = 95,
        color_mode: int = text.COLOR_WHITE,
        color: Color = (255, 255, 255),
        bg_color: Color | None = None,
    ) -> None:
        if self._screen_size == ScreenSize.SIZE_32x32:
            packets = text.build_text_packet_32x32(
                text_value, font_path, font_size, text_mode, speed, color_mode, color, bg_color
            )
            await self._send_packets(packets)
        else:
            await self._send(
                text.build_text_packet(
                    text_value, font_path, font_size, text_mode, speed, color_mode, color, bg_color
                )
            )


class GifFeature(_Feature):
    def __init__(self, transport: BleTransport, screen_size: ScreenSize):
        super().__init__(transport)
        self._canvas_size = screen_size.width  # square canvas

    async def upload_file(
        self,
        file_path: str | PathLike,
        resize_mode: ResizeMode = ResizeMode.FIT,
        do_palettize: bool = True,
        background_color: Color = (0, 0, 0),
        duration_per_frame_ms: int | None = None,
    ) -> None:
        gif_data = gif.adapt_gif(
            file_path, self._canvas_size, resize_mode, do_palettize, background_color, duration_per_frame_ms
        )
        await self._send_packets(gif.build_packets(gif_data))

    async def upload_bytes(self, gif_data: bytes) -> None:
        """Uploads already-adapted GIF bytes without re-processing."""
        await self._send_packets(gif.build_packets(gif_data))


class CommonFeature(_Feature):
    async def set_brightness(self, percent: int) -> None:
        await self._send(common.build_set_brightness(percent))

    async def turn_on(self) -> None:
        await self._send(common.build_set_power(True))

    async def turn_off(self) -> None:
        await self._send(common.build_set_power(False))

    async def set_screen_flipped(self, flipped: bool = True) -> None:
        await self._send(common.build_set_screen_flipped(flipped))

    async def freeze_screen(self) -> None:
        await self._send(common.build_freeze_screen())

    async def set_speed(self, speed: int) -> None:
        await self._send(common.build_set_speed(speed))

    async def set_time(self, when: datetime) -> None:
        await self._send(common.build_set_time(when))

    async def set_joint(self, mode: int) -> None:
        await self._send(common.build_set_joint(mode))

    async def set_password(self, password: int) -> None:
        await self._send(common.build_set_password(password))

    async def verify_password(self, password: int) -> None:
        """Authenticates against a password already set with set_password.

        Fire-and-forget (verify=False) deliberately: verify_password's expected
        ack key is (5, 2), byte-identical to graffiti's out-of-range nack
        [5,0,5,2,0] (docs/APK_SECOND_PASS.md Q4; protocol/response.py). Awaiting
        it by default -- the M2 reject-raises behavior -- would open a pending
        (5, 2) wait that an interleaved graffiti nack could wrongly resolve, so
        this path keeps the pre-M2 no-await behavior. A caller that needs the
        real verify result must await_device_ack it itself, having ensured no
        graffiti write is in flight.
        """
        await self._send(common.build_verify_password(password), verify=False)

    async def set_screen_timeout(self, value: int) -> None:
        """Sets the screen-on / auto-dim timer. Units unknown pending hardware test."""
        await self._send(common.build_set_screen_timeout(value))

    async def read_screen_timeout(self) -> None:
        """Requests a read-back of the screen timeout; reply arrives via the
        device-ack listener (add_response_listener / await_device_ack)."""
        await self._send(common.build_read_screen_timeout())

    async def reset(self) -> None:
        await self._send_packets(common.build_reset())


class ExperimentalFeature(_Feature):
    """Unverified-on-hardware and/or destructive commands.

    Bytes are confirmed from APK decompilation but have not been exercised
    against real reference hardware. Prefer the stable namespaces (client.common,
    etc.) unless you specifically need one of these.
    """

    async def set_time_indicator(self, enabled: bool) -> None:
        """EXPERIMENTAL: toggles a time indicator on the clock face.

        Unverified on our reference hardware — the original research lab reported this
        "doesn't seem to work" on some firmware/models, though the bytes are still
        shipped by the current official app.
        """
        await self._send(common.build_set_time_indicator(enabled))

    async def delete_device_data(self, confirm: bool = False) -> None:
        """EXPERIMENTAL and DESTRUCTIVE: erases device data.

        Never hardware-verified by this driver, and irreversible on the device
        side. Requires confirm=True — raises ValueError otherwise — to reduce the
        chance of an accidental call; there is no further confirmation from the
        device once this is sent.
        """
        if not confirm:
            raise ValueError("delete_device_data is destructive; pass confirm=True to proceed")
        await self._send(common.build_delete_device_data())

    async def schedule_master_switch(self, enable: bool, buzzer: bool) -> None:
        """EXPERIMENTAL: turns the Weekly Schedule feature on/off, with buzzer.

        Flat 5-byte command, ack shape already matches DeviceAck ([5,0,7,0x80,·]).
        Bytes are confirmed from APK decompilation but the enable/buzzer bit order
        (packed = (buzzer << 1) | enable) is derived from a decompiled bit packer,
        not observed on a real device -- unverified on our reference hardware.
        """
        await self._send(schedule.build_master_switch(enable, buzzer))

    async def timer_close(self, timer_obj: timer.Timer) -> None:
        """EXPERIMENTAL: disables a Timer alarm slot without deleting it.

        Flat 12-byte command (sendCloseData), no chunking, no payload. Unverified
        on our reference hardware, and its ack (if any) is a different, richer 3-way
        status vocabulary than the usual DeviceAck accept/reject -- see
        protocol.response.StatusAck. For uploading an alarm's custom content, see
        timer_set below.
        """
        await self._send(timer.build_timer_close(timer_obj))

    async def timer_set(self, timer_obj: timer.Timer, payload: bytes) -> None:
        """EXPERIMENTAL: uploads an alarm slot's custom image/GIF/text content
        (Timer sendData).

        HARDWARE-VERIFIED handshake (2026-07-12, real 32x32 panel): sends each
        outer chunk from protocol.timer.build_timer_data_packets as a
        write-with-response, then waits for the matching StatusAck before
        sending the next one -- see _send_chunked_upload. Raises UploadError if
        the device reports STATUS_FAILED for a chunk, or if no ack arrives
        within the timeout.

        `payload` format depends on content_type. With CONTENT_GIF, it must be
        an encoded GIF bytestream (the same encoding protocol/gif.py produces)
        -- CONFIRMED on hardware: renders animated at fire time, buzzer
        included. With CONTENT_IMAGE, it must be an encoded PNG bytestream --
        HARDWARE-CONFIRMED 2026-07-21 (probes/probe_content_image_and_recolor
        .py): a PNG payload fired and RENDERED at alarm time, while raw
        width*height*3 RGB was SAVED but never rendered (2026-07-12). The
        earlier raw-RGB reading of APK_SECOND_PASS.md Q2 described the
        pre-encoding pixel source, not the wire payload. At fire
        time the panel shows the clock for a few seconds before the alarm's
        content takes over -- expected, not a bug. Set the device's clock
        (client.common.set_time) before relying on a Timer firing at the
        intended wall-clock time.
        """
        chunks = timer.build_timer_data_packets(timer_obj, payload)
        await _send_chunked_upload(self._transport, chunks, ack_type=0x00, ack_subtype=0x80, label="timer")

    async def schedule_set_theme(self, theme: schedule.ScheduleTheme, payload: bytes, content: int) -> None:
        """EXPERIMENTAL: uploads a Weekly Schedule theme's recurring content
        (Schedule gifSolve/per-theme upload).

        HARDWARE-VERIFIED handshake (2026-07-12, real 32x32 panel): same
        send-chunk / await-StatusAck loop as timer_set (see
        _send_chunked_upload) -- a real upload completed with StatusAck
        status=SAVED, which is what motivated dispatching this ack family as
        StatusAck instead of a plain DeviceAck (see protocol.response). Raises
        UploadError on STATUS_FAILED or ack timeout.

        `payload` format depends on content. With schedule.CONTENT_GIF, it must
        be an encoded GIF bytestream, mirroring Timer's confirmed content_type
        behavior (see timer_set). With schedule.CONTENT_IMAGE, it must be a
        single-frame PNG (CONFIRMED-FROM-SOURCE, docs/APK_SECOND_PASS.md Q2) --
        NOT raw RGB like Timer's CONTENT_IMAGE, a genuine asymmetry between the
        two features. Both content types are accepted by the builder, but
        on-device rendering for either is hardware-untested for Schedule. The
        week byte's encoding is understood (see protocol/schedule.py's
        ScheduleTheme/patch_week docstrings and build_schedule_week), but which
        physical day the device fires on for a given bit, and the theme's
        active-window behavior, remain unverified -- see
        probes/probe_schedule_gif.py.
        """
        chunks = schedule.build_schedule_theme_packets(theme, payload, content)
        await _send_chunked_upload(self._transport, chunks, ack_type=0x05, ack_subtype=0x80, label="schedule theme")


class IDotMatrixClient:
    """Full-feature client for one iDotMatrix device.

    `display` is the frame-pipeline backend (show_frame / set_pixels). The feature
    namespaces command native device modes. All share one connection.
    """

    def __init__(
        self,
        screen_size: ScreenSize,
        mac_address: str | None = None,
        transport: BleTransport | None = None,
        verify_commands: bool = True,
    ):
        self._transport = transport or BleTransport(mac_address)
        self.screen_size = screen_size
        self.display = BleDisplay(screen_size, self._transport)

        self.chronograph = ChronographFeature(self._transport)
        self.countdown = CountdownFeature(self._transport)
        self.clock = ClockFeature(self._transport)
        self.scoreboard = ScoreboardFeature(self._transport)
        self.eco = EcoFeature(self._transport)
        self.color = FullscreenColorFeature(self._transport)
        self.graffiti = GraffitiFeature(self._transport, screen_size)
        self.effect = EffectFeature(self._transport)
        self.music_sync = MusicSyncFeature(self._transport)
        self.text = TextFeature(self._transport, screen_size)
        self.gif = GifFeature(self._transport, screen_size)
        self.common = CommonFeature(self._transport)
        self.experimental = ExperimentalFeature(self._transport)

        self._features = (
            self.chronograph, self.countdown, self.clock, self.scoreboard, self.eco,
            self.color, self.graffiti, self.effect, self.music_sync, self.text,
            self.gif, self.common, self.experimental,
        )
        if not verify_commands:
            self.set_command_verification(False)

    def set_command_verification(self, enabled: bool) -> None:
        """Turns per-command ack verification on or off across every feature
        namespace. When off, feature calls fire-and-forget instead of awaiting
        the device ack and raising CommandRejectedError on a nack -- the pre-M2
        behavior, useful for latency-sensitive or best-effort callers.

        Individual paths that must always fire-and-forget (graffiti,
        verify_password) are unaffected: they opt out at the call site
        regardless of this flag.
        """
        for feature in self._features:
            feature._verify_commands = enabled

    @classmethod
    def connect_to(
        cls,
        device: "DeviceInfo | str",
        screen_size: ScreenSize,
        **kwargs: Any,
    ) -> "IDotMatrixClient":
        """Constructs a client for a DeviceInfo (from discover()) or a MAC string.

        The actual connect happens on `async with` entry (__aenter__), so this
        reads naturally as `async with IDotMatrixClient.connect_to(dev, size) as
        client:`. Extra kwargs pass through to __init__.
        """
        address = device.address if isinstance(device, DeviceInfo) else device
        return cls(screen_size, mac_address=address, **kwargs)

    async def __aenter__(self) -> "IDotMatrixClient":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._transport.is_connected

    @property
    def auto_reconnect(self) -> bool:
        return self._transport.auto_reconnect

    async def connect(self) -> None:
        await self._transport.connect()

    async def disconnect(self) -> None:
        await self._transport.disconnect()

    def set_auto_reconnect(self, enabled: bool) -> None:
        """Enables/disables reconnect supervision at runtime."""
        self._transport.set_auto_reconnect(enabled)

    def add_listener(
        self,
        on_connected: ConnectionCallback | None = None,
        on_disconnected: ConnectionCallback | None = None,
    ) -> Callable[[], None]:
        """Registers async connection-state callbacks. Returns an unsubscribe callable."""
        return self._transport.add_listener(on_connected, on_disconnected)

    def add_response_listener(self, callback: Callable[[DeviceAck | StatusAck], None]) -> Callable[[], None]:
        """Registers a callback for device acks. Returns an unsubscribe callable."""
        return self._transport.add_response_listener(callback)

    def add_event_listener(self, callback: Callable[[TransportEvent], None]) -> Callable[[], None]:
        """Registers a callback for transport events. Returns an unsubscribe callable."""
        return self._transport.add_event_listener(callback)

    def snapshot(self) -> TransportSnapshot:
        """A read-only view of the connection state (for observability)."""
        return self._transport.snapshot()

    async def await_device_ack(self, command: bytearray, timeout: float = 2.0) -> DeviceAck | StatusAck | None:
        """Sends a command and returns the device's ack, or None on timeout.

        Returns a plain DeviceAck (accepted/rejected) for ordinary commands, or
        a StatusAck (the NEXT_CHUNK/SAVED/FAILED family) if the command's
        (type, subtype) is one of the chunked-upload keys -- see
        BleTransport.await_device_ack's docstring for the full breakdown.
        Command bytes come from the protocol builders, e.g.
        await_device_ack(protocol.common.build_set_brightness(60)).
        """
        return await self._transport.await_device_ack(command, timeout)

    async def show_image(
        self,
        image: Image.Image | str | PathLike,
        resize_mode: ResizeMode = ResizeMode.FIT,
        background_color: Color = (0, 0, 0),
        do_palettize: bool = False,
        wait_for_device: bool = True,
    ) -> None:
        """Convenience: adapt an image (or path) to the screen and show it as a frame."""
        rgb = adapt_image(image, self.screen_size.width, resize_mode, background_color, do_palettize)
        await self.display.show_frame(rgb, wait_for_device=wait_for_device)
