"""The exception hierarchy is importable from the package root and correctly shaped."""

import pyidotmatrix
from pyidotmatrix.exceptions import (
    CommandRejectedError,
    ConnectionLostError,
    IDotMatrixError,
    UploadError,
)
from pyidotmatrix.protocol.response import DeviceAck


def test_exceptions_are_exported_from_package_root():
    for name in ("IDotMatrixError", "ConnectionLostError", "CommandRejectedError", "UploadError"):
        assert hasattr(pyidotmatrix, name)
        assert name in pyidotmatrix.__all__


def test_every_error_subclasses_the_base():
    for cls in (ConnectionLostError, CommandRejectedError, UploadError):
        assert issubclass(cls, IDotMatrixError)


def test_command_rejected_carries_raw_and_parsed_ack():
    ack = DeviceAck(command_type=7, command_subtype=8, accepted=False, raw=bytes([5, 0, 7, 8, 0]))
    error = CommandRejectedError(ack)
    assert error.ack is ack
    assert error.raw == bytes([5, 0, 7, 8, 0])
    assert "type=7" in str(error) and "subtype=8" in str(error)


def test_chunked_upload_error_is_an_upload_error():
    # Back-compat alias: the old name still resolves, now under the hierarchy.
    from pyidotmatrix.client import ChunkedUploadError

    assert ChunkedUploadError is UploadError
    assert issubclass(ChunkedUploadError, IDotMatrixError)
