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

    Not raised yet: today disconnects and failed writes still surface as bleak
    errors. Mapping them to this type is the remaining SDK-M2 exception work;
    the class ships now so callers can write the except clause against the
    stable name.
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
    """A chunked upload failed: the device reported StatusAck FAILED, no ack
    arrived within the timeout, or the connection dropped mid-upload."""
