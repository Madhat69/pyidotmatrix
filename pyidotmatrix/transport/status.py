"""Read-only transport status and events, for observability.

The daemon publishes these; the driver only produces them. All frozen so a
snapshot can't be mutated by the consumer.
"""

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class TransportSnapshot:
    """A point-in-time view of one transport's connection."""

    address: str | None
    is_connected: bool
    write_size: int | None         # negotiated no-response write size; None until first write
    reconnect_count: int              # successful reconnects since creation
    last_failure: str | None       # human-readable, most recent
    last_failure_at: float | None  # unix time of last_failure


class TransportEventKind(Enum):
    WRITE_FAILED = "write_failed"
    RECONNECT_STARTED = "reconnect_started"
    RECONNECT_ATTEMPT = "reconnect_attempt"  # about to rebuild the BleakClient and retry
    RECONNECT_SUCCEEDED = "reconnect_succeeded"


@dataclass(frozen=True)
class TransportEvent:
    kind: TransportEventKind
    detail: str | None = None
