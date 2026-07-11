"""IDotMatrixClient: the full-feature facade over one device connection.

Groups every native device capability into namespaces (client.clock, client.countdown,
...) that share a single BleTransport with the frame-pipeline backend (client.display).
A caller can render frames through `display` and command native modes through the
feature namespaces over the same connection.

Config commands are written with response=True: the GATT write acknowledgement is
the device's flow-control signal, so no inter-command sleeps are needed.
"""

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
    scoreboard,
    text,
)
from idotmatrix.protocol.response import DeviceAck
from idotmatrix.screen import ScreenSize
from idotmatrix.transport.ble import BleTransport
from idotmatrix.transport.status import TransportEvent, TransportSnapshot

Color = tuple[int, int, int]


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
    against real GlanceOS hardware. Prefer the stable namespaces (client.common,
    etc.) unless you specifically need one of these.
    """

    async def set_time_indicator(self, enabled: bool) -> None:
        """EXPERIMENTAL: toggles a time indicator on the clock face.

        Unverified on GlanceOS hardware — the original research lab reported this
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
        self.text = TextFeature(self._transport)
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

    def add_listener(self, on_connected=None, on_disconnected=None) -> Callable[[], None]:
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
