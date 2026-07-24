# Public API Reference

Hand-curated from the actual public signatures in `pyidotmatrix/` — every
entry below matches its source file at the time of writing. If you find a
mismatch, the source is authoritative; please file it as a doc bug. This page
covers `pyidotmatrix.__all__`, i.e. everything importable directly from the
top-level package:

```python
from pyidotmatrix import (
    ScreenSize, DisplayBackend, BleDisplay, SimulatorDisplay,
    IDotMatrixClient, BleTransport, DeviceInfo, discover, discover_devices,
    ResizeMode, adapt_image,
    TransportSnapshot, TransportEvent, TransportEventKind,
    IDotMatrixError, ConnectionLostError, CommandRejectedError, UploadError,
    CAPABILITIES, Capability, CapabilityStatus, capability,
)
```

## Discovery

```python
async def discover(name_prefix: str = "IDM-") -> list[DeviceInfo]
async def discover_devices(name_prefix: str = "IDM-") -> list[str]   # bare MAC strings

@dataclass(frozen=True)
class DeviceInfo:
    name: str
    address: str
    rssi: int | None = None
```

`discover()` is the rich form (prefer it); `discover_devices()` predates it
and returns bare MAC address strings.

## `ScreenSize`

```python
class ScreenSize(Enum):
    SIZE_16x16 = (16, 16)
    SIZE_32x32 = (32, 32)
    SIZE_64x64 = (64, 64)

    width: int
    height: int
    pixel_count: int
```

Not validated against the actual connected device — see
`docs/ROADMAP.md` §16.3.

## `IDotMatrixClient`

```python
class IDotMatrixClient:
    def __init__(
        self,
        screen_size: ScreenSize,
        mac_address: str | None = None,
        transport: BleTransport | None = None,
        verify_commands: bool = True,
    ): ...

    @classmethod
    def connect_to(cls, device: DeviceInfo | str, screen_size: ScreenSize, **kwargs) -> IDotMatrixClient: ...

    async def __aenter__(self) -> IDotMatrixClient: ...   # calls connect()
    async def __aexit__(self, ...) -> None: ...            # calls disconnect()

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    @property
    def is_connected(self) -> bool: ...
    @property
    def auto_reconnect(self) -> bool: ...
    def set_auto_reconnect(self, enabled: bool) -> None: ...

    def set_command_verification(self, enabled: bool) -> None: ...

    def add_listener(self, on_connected=None, on_disconnected=None) -> Callable[[], None]: ...
    def add_response_listener(self, callback: Callable[[DeviceAck | StatusAck], None]) -> Callable[[], None]: ...
    def add_event_listener(self, callback: Callable[[TransportEvent], None]) -> Callable[[], None]: ...
    def snapshot(self) -> TransportSnapshot: ...

    async def await_device_ack(self, command: bytearray, timeout: float = 2.0) -> DeviceAck | None: ...

    async def show_image(
        self,
        image: Image.Image | str | PathLike,
        resize_mode: ResizeMode = ResizeMode.FIT,
        background_color: tuple[int, int, int] = (0, 0, 0),
        do_palettize: bool = False,
        wait_for_device: bool = True,
    ) -> None: ...

    # feature namespaces, all sharing one BleTransport:
    display: BleDisplay
    chronograph: ChronographFeature
    countdown: CountdownFeature
    clock: ClockFeature
    scoreboard: ScoreboardFeature
    eco: EcoFeature
    color: FullscreenColorFeature
    graffiti: GraffitiFeature
    effect: EffectFeature
    music_sync: MusicSyncFeature
    text: TextFeature
    gif: GifFeature
    common: CommonFeature
    experimental: ExperimentalFeature
```

`screen_size` is required and trusted — see
[Getting Started § Connect](getting-started.md#3-connect). `verify_commands`
(default `True`) makes every feature-namespace call await the device's ack
and raise `CommandRejectedError` on a nack; `set_command_verification(False)`
flips this at runtime for every namespace at once. `mac_address=None` +
`transport=None` connects to the first discovered device.

## Feature namespaces

Every method below is `async`. Full usage examples with maturity tags:
[Feature Guide](features.md).

```python
class ChronographFeature:
    async def reset(self) -> None: ...
    async def start(self) -> None: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...

class CountdownFeature:
    async def start(self, minutes: int, seconds: int = 0) -> None: ...
    async def stop(self) -> None: ...
    async def pause(self) -> None: ...
    async def restart(self) -> None: ...

class ClockFeature:
    async def show(
        self, style: int = 0, show_date: bool = True, hour24: bool = True,
        color: tuple[int, int, int] = (255, 255, 255),
    ) -> None: ...

class ScoreboardFeature:
    async def show(self, count1: int, count2: int) -> None: ...

class EcoFeature:
    async def set_mode(
        self, enabled: bool = True,
        start_hour: int = 22, start_minute: int = 0,
        end_hour: int = 6, end_minute: int = 0,
        eco_brightness: int = 10,
    ) -> None: ...

class FullscreenColorFeature:
    async def show(self, color: tuple[int, int, int]) -> None: ...

class GraffitiFeature:
    async def set_pixels(
        self, color: tuple[int, int, int], xys: list[tuple[int, int]],
        move_type: int = 0,   # graffiti.MOVE_NONE
    ) -> None: ...

class EffectFeature:
    async def show(self, style: int, colors: list[tuple[int, int, int]], speed: int = 90) -> None: ...
    async def show_chunked(
        self, style: int, colors: list[tuple[int, int, int]],
        speed: int = 90, mtu_negotiated: bool = True,
    ) -> None: ...

class MusicSyncFeature:
    async def set_mic_type(self, mic_type: int) -> None: ...
    async def send_image_rhythm(self, value: int) -> None: ...
    async def stop_rhythm(self) -> None: ...

class TextFeature:
    async def show(
        self, text_value: str, font_path: str, font_size: int = 16,
        text_mode: int = 1,          # text.MODE_MARQUEE
        speed: int = 95,
        color_mode: int = 0,         # text.COLOR_WHITE
        color: tuple[int, int, int] = (255, 255, 255),
        bg_color: tuple[int, int, int] | None = None,
    ) -> None: ...

class GifFeature:
    async def upload_file(
        self, file_path: str | PathLike,
        resize_mode: ResizeMode = ResizeMode.FIT,
        do_palettize: bool = True,
        background_color: tuple[int, int, int] = (0, 0, 0),
        duration_per_frame_ms: int | None = None,
    ) -> None: ...
    async def upload_bytes(self, gif_data: bytes) -> None: ...

class CommonFeature:
    async def set_brightness(self, percent: int) -> None: ...
    async def turn_on(self) -> None: ...
    async def turn_off(self) -> None: ...
    async def set_screen_flipped(self, flipped: bool = True) -> None: ...
    async def freeze_screen(self) -> None: ...              # ✖ known-broken
    async def set_speed(self, speed: int) -> None: ...       # ✖ known-broken
    async def set_time(self, when: datetime) -> None: ...
    async def set_joint(self, mode: int) -> None: ...        # ❓ unknown
    async def set_password(self, password: int) -> None: ...       # ⚠ never hardware-tested
    async def verify_password(self, password: int) -> None: ...    # ⚠ never hardware-tested, always fire-and-forget
    async def set_screen_timeout(self, value: int) -> None: ...    # ✖ known-broken
    async def read_screen_timeout(self) -> None: ...               # ✖ known-broken
    async def reset(self) -> None: ...

class ExperimentalFeature:
    async def set_time_indicator(self, enabled: bool) -> None: ...          # ✖ known-broken
    async def delete_device_data(self, confirm: bool = False) -> None: ...  # destructive, raises ValueError without confirm=True
    async def schedule_master_switch(self, enable: bool, buzzer: bool) -> None: ...
    async def timer_close(self, timer_obj: timer.Timer) -> None: ...
    async def timer_set(self, timer_obj: timer.Timer, payload: bytes) -> None: ...
    async def schedule_set_theme(self, theme: schedule.ScheduleTheme, payload: bytes, content: int) -> None: ...
```

## `DisplayBackend` / `BleDisplay` / `SimulatorDisplay`

```python
@runtime_checkable
class DisplayBackend(Protocol):
    id: str
    width: int
    height: int
    @property
    def is_connected(self) -> bool: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def show_frame(self, rgb: bytes, wait_for_device: bool = True) -> None: ...
    async def set_pixels(self, color, xys: list[tuple[int, int]], wait_for_device: bool = False) -> None: ...
    async def set_brightness(self, percent: int) -> None: ...
    async def set_power(self, on: bool) -> None: ...
    def add_listener(self, on_connected=None, on_disconnected=None) -> None: ...
```

`BleDisplay(screen_size, transport, id="ble")` and
`SimulatorDisplay(screen_size, id="simulator", emulate_timing=False, on_frame=None)`
both satisfy this protocol. `SimulatorDisplay` additionally exposes
`.framebuffer` (a `bytes` snapshot), `.brightness`, and `.power` for
assertions/preview, and `emulate_timing=True` reproduces the measured
device costs (1.5 s per full frame, 20 ms per pixel command) without
hardware.

`BleDisplay` also exposes two DIY-mode-entry knobs beyond the protocol:
`set_entry_clear(clear: bool)` (choose the clear/no-clear DIY entry mode for
the *next* entry) and `invalidate_diy_mode()` (tell it something else — a
native mode sent through another namespace on the same connection — took the
panel out of DIY mode). See the docstrings in
`pyidotmatrix/display/ble_display.py` for the full hardware rationale.

## `BleTransport`

```python
class BleTransport:
    def __init__(
        self,
        mac_address: str | None = None,
        auto_reconnect: bool = True,
        write_size_override: int | None = None,
    ): ...

    @property
    def is_connected(self) -> bool: ...
    @property
    def is_write_ready(self) -> bool: ...
    @property
    def auto_reconnect(self) -> bool: ...

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    def set_auto_reconnect(self, enabled: bool) -> None: ...

    async def write(self, data: bytes | bytearray, response: bool = False) -> None: ...
    async def write_packets(self, packets: list[list[bytearray]], response: bool = False) -> None: ...
    async def await_device_ack(self, command: bytes | bytearray, timeout: float = 2.0) -> DeviceAck | None: ...

    def snapshot(self) -> TransportSnapshot: ...
    def add_listener(self, on_connected=None, on_disconnected=None) -> Callable[[], None]: ...
    def add_response_listener(self, callback) -> Callable[[], None]: ...
    def add_event_listener(self, callback) -> Callable[[], None]: ...
```

`write_size_override` is the BlueZ low-MTU escape hatch — see
[Protocol Notes § Low-MTU panels on BlueZ](protocol-notes.md#low-mtu-panels-on-bluez).
`await_device_ack` raises `ValueError` for graffiti commands (genuinely
ack-silent on the wire) and if a wait is already pending for the same
command's (type, subtype) key.

## Exceptions

```python
class IDotMatrixError(Exception): ...              # base of the hierarchy

class ConnectionLostError(IDotMatrixError): ...     # reserved; not yet raised anywhere (see class docstring)

class CommandRejectedError(IDotMatrixError):
    ack: DeviceAck
    raw: bytes
    def __init__(self, ack: DeviceAck): ...

class UploadError(IDotMatrixError): ...             # chunked upload FAILED, timed out, or dropped mid-upload
```

`ChunkedUploadError` (from `pyidotmatrix.client`) is a back-compat alias for
`UploadError` — both catch the same exception.

## Imaging

```python
class ResizeMode(Enum):
    FIT = "fit"          # keep aspect ratio, letterbox with background_color
    FILL = "fill"        # keep aspect ratio, crop overflow
    STRETCH = "stretch"  # ignore aspect ratio

def adapt_image(
    image: Image.Image | str | PathLike,
    canvas_size: int,
    resize_mode: ResizeMode = ResizeMode.FIT,
    background_color: tuple[int, int, int] = (0, 0, 0),
    do_palettize: bool = False,
) -> bytes: ...   # returns RGB bytes ready for show_frame
```

## Observability types

```python
@dataclass(frozen=True)
class TransportSnapshot:
    address: str | None
    is_connected: bool
    write_size: int | None
    reconnect_count: int
    last_failure: str | None
    last_failure_at: float | None

class TransportEventKind(Enum):
    WRITE_FAILED = "write_failed"
    RECONNECT_STARTED = "reconnect_started"
    RECONNECT_ATTEMPT = "reconnect_attempt"
    RECONNECT_SUCCEEDED = "reconnect_succeeded"

@dataclass(frozen=True)
class TransportEvent:
    kind: TransportEventKind
    detail: str | None = None
```

## Capability table

```python
class CapabilityStatus(Enum):
    VERIFIED = "verified"
    SOURCE_DERIVED = "source_derived"
    UNKNOWN = "unknown"
    KNOWN_BROKEN = "known_broken"

@dataclass(frozen=True)
class Capability:
    feature: str
    command: str
    status: CapabilityStatus
    screen_size: ScreenSize | None
    evidence: str
    @property
    def name(self) -> str: ...   # "{feature}.{command}"

CAPABILITIES: Mapping[str, Capability]   # read-only, keyed by "feature.command"

def capability(name: str) -> Capability: ...   # raises KeyError (listing known names) if absent
```

See [Hardware Compatibility](hardware-compatibility.md) for the full,
rendered table.
