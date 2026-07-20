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
from typing import Optional

from idotmatrix.display.ble_display import BleDisplay
from idotmatrix.imaging import ResizeMode, adapt_image
from idotmatrix.protocol import (
    chronograph,
    clock,
    common,
    countdown,
    effect,
    eco,
    fullscreen_color,
    gif,
    graffiti,
    music_sync,
    schedule,
    scoreboard,
    text,
    timer,
)
from idotmatrix.protocol.response import STATUS_FAILED, STATUS_SAVED, DeviceAck, StatusAck
from idotmatrix.screen import ScreenSize
from idotmatrix.transport.ble import BleTransport, ConnectionCallback
from idotmatrix.transport.status import TransportEvent, TransportSnapshot

Color = tuple[int, int, int]

# How long to wait for a StatusAck after sending one outer chunk of a Timer/
# Schedule chunked upload. HARDWARE-CONFIRMED 2026-07-12: a real device replies
# within well under this on a 32x32 panel; 5s leaves headroom for BLE jitter.
_CHUNK_ACK_TIMEOUT_SECONDS = 5.0


class ChunkedUploadError(RuntimeError):
    """Raised when a Timer/Schedule chunked upload is rejected (StatusAck
    STATUS_FAILED) or no ack arrives for an outer chunk within the timeout."""


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
    hardware-confirmed 2026-07-12). FAILED -> raise ChunkedUploadError.
    Timeout waiting for an ack -> raise ChunkedUploadError.

    Duplicate StatusAck frames (hardware sends them -- the same status
    observed twice for one chunk) are tolerated by draining any ack still
    sitting in the queue from the previous chunk before sending the next one.
    """
    acks: asyncio.Queue = asyncio.Queue()

    def _on_ack(ack) -> None:
        if isinstance(ack, StatusAck) and ack.command_type == ack_type and ack.command_subtype == ack_subtype:
            acks.put_nowait(ack)

    unsubscribe = transport.add_response_listener(_on_ack)
    try:
        for index, chunk in enumerate(chunks):
            _drain_stale_acks(acks)  # discard a duplicate left over from the previous chunk
            await transport.write_packets([chunk], response=True)
            try:
                ack = await asyncio.wait_for(acks.get(), _CHUNK_ACK_TIMEOUT_SECONDS)
            except asyncio.TimeoutError as ex:
                raise ChunkedUploadError(
                    f"{label} upload: no ack within {_CHUNK_ACK_TIMEOUT_SECONDS}s after "
                    f"chunk {index + 1}/{len(chunks)}"
                ) from ex

            if ack.status == STATUS_SAVED:
                return  # early SAVED is expected for single-chunk uploads; tolerate it any time
            if ack.status == STATUS_FAILED:
                raise ChunkedUploadError(
                    f"{label} upload rejected (status=FAILED) at chunk {index + 1}/{len(chunks)}"
                )
            # STATUS_NEXT_CHUNK (or any other value): proceed to the next chunk.
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

    def __init__(self, transport: BleTransport):
        self._transport = transport

    async def _send(self, data: bytearray) -> None:
        await self._transport.write(data, response=True)

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

    The frame pipeline uses display.set_pixels (mirror off) for deltas; this
    namespace exists for graffiti drawing that wants the mirror modes.
    """

    async def set_pixels(
        self,
        color: Color,
        xys: list[tuple[int, int]],
        mirror: int = graffiti.MIRROR_NONE,
    ) -> None:
        for start in range(0, len(xys), graffiti.MAX_PIXELS_PER_COMMAND):
            batch = xys[start:start + graffiti.MAX_PIXELS_PER_COMMAND]
            await self._send(graffiti.build_set_pixels(color, batch, mirror))


class EffectFeature(_Feature):
    async def show(self, style: int, colors: list[Color]) -> None:
        await self._send(effect.build_show(style, colors))


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

    def __init__(self, transport: BleTransport, screen_size: Optional[ScreenSize] = None):
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
        bg_color: Optional[Color] = None,
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
        file_path,
        resize_mode: ResizeMode = ResizeMode.FIT,
        do_palettize: bool = True,
        background_color: Color = (0, 0, 0),
        duration_per_frame_ms: Optional[int] = None,
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
        """Authenticates against a password already set with set_password."""
        await self._send(common.build_verify_password(password))

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
        sending the next one -- see _send_chunked_upload. Raises
        ChunkedUploadError if the device reports STATUS_FAILED for a chunk, or
        if no ack arrives within the timeout.

        `payload` format depends on content_type. With CONTENT_GIF, it must be
        an encoded GIF bytestream (the same encoding protocol/gif.py produces)
        -- CONFIRMED on hardware: renders animated at fire time, buzzer
        included. With CONTENT_IMAGE, it must be raw, uncompressed RGB, no
        header: exactly width*height*3 bytes, row-major, [R,G,B] per pixel
        (CONFIRMED-FROM-SOURCE, docs/APK_SECOND_PASS.md Q2 -- byte-identical to
        the app's own image-alarm path). Our one hardware test of
        CONTENT_IMAGE used a payload with an accidentally big-endian duration
        header (a test bug, not a format bug); the device accepted and saved
        it (StatusAck status=SAVED) but rendering is UNVERIFIED-PENDING-RETEST
        -- do not treat that result as CONTENT_IMAGE being broken. At fire
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
        ChunkedUploadError on STATUS_FAILED or ack timeout.

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
        mac_address: Optional[str] = None,
        transport: Optional[BleTransport] = None,
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
        self.graffiti = GraffitiFeature(self._transport)
        self.effect = EffectFeature(self._transport)
        self.music_sync = MusicSyncFeature(self._transport)
        self.text = TextFeature(self._transport, screen_size)
        self.gif = GifFeature(self._transport, screen_size)
        self.common = CommonFeature(self._transport)
        self.experimental = ExperimentalFeature(self._transport)

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
        on_connected: Optional[ConnectionCallback] = None,
        on_disconnected: Optional[ConnectionCallback] = None,
    ) -> Callable[[], None]:
        """Registers async connection-state callbacks. Returns an unsubscribe callable."""
        return self._transport.add_listener(on_connected, on_disconnected)

    def add_response_listener(self, callback: Callable[[DeviceAck], None]) -> Callable[[], None]:
        """Registers a callback for device acks. Returns an unsubscribe callable."""
        return self._transport.add_response_listener(callback)

    def add_event_listener(self, callback: Callable[[TransportEvent], None]) -> Callable[[], None]:
        """Registers a callback for transport events. Returns an unsubscribe callable."""
        return self._transport.add_event_listener(callback)

    def snapshot(self) -> TransportSnapshot:
        """A read-only view of the connection state (for observability)."""
        return self._transport.snapshot()

    async def await_device_ack(self, command: bytearray, timeout: float = 2.0) -> Optional[DeviceAck]:
        """Sends a command and returns the device's ack, or None on timeout.

        Command bytes come from the protocol builders, e.g.
        await_device_ack(protocol.common.build_set_brightness(60)).
        """
        return await self._transport.await_device_ack(command, timeout)

    async def show_image(
        self,
        image,
        resize_mode: ResizeMode = ResizeMode.FIT,
        background_color: Color = (0, 0, 0),
        do_palettize: bool = False,
        wait_for_device: bool = True,
    ) -> None:
        """Convenience: adapt an image (or path) to the screen and show it as a frame."""
        rgb = adapt_image(image, self.screen_size.width, resize_mode, background_color, do_palettize)
        await self.display.show_frame(rgb, wait_for_device=wait_for_device)
