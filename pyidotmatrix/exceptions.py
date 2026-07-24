"""The driver's exception hierarchy.

One base (IDotMatrixError) so callers can catch every driver-raised error with a
single except clause, with narrower types for the three failure modes worth
distinguishing: a lost connection, a command the device explicitly rejected, and
a chunked upload that failed.
"""

from pyidotmatrix.protocol.response import DeviceAck


class IDotMatrixError(Exception):
    """Base for every error this driver raises."""


class ConnectionLostError(IDotMatrixError):
    """The transport lost the connection to the device.

    Raised by BleTransport._write_raw (transport/ble.py) when a write fails and
    the transport's one-shot self-heal (a forced reconnect-and-retry) is
    exhausted -- either the reconnect itself fails, or it succeeds but the
    retried write fails too. In both cases this is raised chained (`raise ...
    from e`) from the underlying bleak exception, so callers get a stable
    driver-level type instead of a raw bleak error, while `__cause__` still
    carries the original for diagnostics.
    """


class CommandRejectedError(IDotMatrixError):
    """The device nacked a command (a boolean DeviceAck with accepted=False).

    Carries the parsed ack and its raw bytes so callers can inspect which
    command (type/subtype) was rejected. Not raised for a StatusAck -- a
    chunked-upload status frame (including SAVED) is never a rejection; see
    protocol/response.py.
    """

    def __init__(self, ack: DeviceAck):
        self.ack = ack
        self.raw = ack.raw
        super().__init__(
            f"device rejected command type={ack.command_type} subtype={ack.command_subtype} "
            f"(raw {ack.raw.hex()})"
        )


class UploadError(IDotMatrixError):
    """A chunked upload failed: the device reported StatusAck FAILED (or any
    status this driver doesn't recognize), no ack arrived within the timeout,
    or every chunk sent without ever seeing a terminal SAVED status.

    `raw` carries the failing StatusAck's raw bytes when one was received
    (FAILED or unrecognized status); it is None when the failure had no ack to
    point to (a timeout, or exhausting all chunks without a SAVED).
    """

    def __init__(self, message: str, raw: bytes | None = None):
        super().__init__(message)
        self.raw = raw
