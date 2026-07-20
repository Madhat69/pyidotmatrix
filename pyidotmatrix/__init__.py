"""idotmatrix — an opinion-free driver for iDotMatrix BLE pixel displays.

Public surface:
    IDotMatrixClient                 full-feature client facade
    ScreenSize                       supported display sizes
    DisplayBackend                   the interface every backend satisfies
    BleDisplay / SimulatorDisplay    hardware and in-memory implementations
    BleTransport                     BLE connection primitive
    discover / DeviceInfo            rich device discovery
    discover_devices                 discovery returning bare MAC strings
    ResizeMode / adapt_image         image adaptation helpers
    TransportSnapshot / TransportEvent / TransportEventKind
                                      connection observability
    IDotMatrixError                  base of the exception hierarchy
    ConnectionLostError / CommandRejectedError / UploadError
                                      narrower failure types

The driver builds protocol bytes and moves them to the device. It holds no
scheduling, rendering, delta, or app logic — that belongs to callers.
"""

from pyidotmatrix.client import IDotMatrixClient
from pyidotmatrix.display import BleDisplay, DisplayBackend, SimulatorDisplay
from pyidotmatrix.exceptions import (
    CommandRejectedError,
    ConnectionLostError,
    IDotMatrixError,
    UploadError,
)
from pyidotmatrix.imaging import ResizeMode, adapt_image
from pyidotmatrix.screen import ScreenSize
from pyidotmatrix.transport import BleTransport, DeviceInfo, discover, discover_devices
from pyidotmatrix.transport.status import TransportEvent, TransportEventKind, TransportSnapshot

__all__ = [
    "ScreenSize",
    "DisplayBackend",
    "BleDisplay",
    "SimulatorDisplay",
    "IDotMatrixClient",
    "BleTransport",
    "DeviceInfo",
    "discover",
    "discover_devices",
    "ResizeMode",
    "adapt_image",
    "TransportSnapshot",
    "TransportEvent",
    "TransportEventKind",
    "IDotMatrixError",
    "ConnectionLostError",
    "CommandRejectedError",
    "UploadError",
]
