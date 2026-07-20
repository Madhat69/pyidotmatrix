"""idotmatrix — an opinion-free driver for iDotMatrix BLE pixel displays.

Public surface:
    IDotMatrixClient                 full-feature client facade
    ScreenSize                       supported display sizes
    DisplayBackend                   the interface every backend satisfies
    BleDisplay / SimulatorDisplay    hardware and in-memory implementations
    BleTransport / discover_devices  BLE connection primitives
    ResizeMode / adapt_image         image adaptation helpers
    TransportSnapshot / TransportEvent / TransportEventKind
                                      connection observability

The driver builds protocol bytes and moves them to the device. It holds no
scheduling, rendering, delta, or app logic — that belongs to callers.
"""

from idotmatrix.client import IDotMatrixClient
from idotmatrix.display import BleDisplay, DisplayBackend, SimulatorDisplay
from idotmatrix.imaging import ResizeMode, adapt_image
from idotmatrix.screen import ScreenSize
from idotmatrix.transport import BleTransport, discover_devices
from idotmatrix.transport.status import TransportEvent, TransportEventKind, TransportSnapshot

__all__ = [
    "ScreenSize",
    "DisplayBackend",
    "BleDisplay",
    "SimulatorDisplay",
    "IDotMatrixClient",
    "BleTransport",
    "discover_devices",
    "ResizeMode",
    "adapt_image",
    "TransportSnapshot",
    "TransportEvent",
    "TransportEventKind",
]
