"""Shelly RPC exceptions."""

from __future__ import annotations


class RpcError(Exception):
    """Base Shelly RPC error."""


class RpcUnavailableError(RpcError):
    """Transport or target is unavailable."""


class RpcTimeoutError(RpcUnavailableError):
    """RPC call timed out."""


class RpcAuthError(RpcError):
    """Authentication failed or is required."""


class RpcProtocolError(RpcError):
    """Malformed or unexpected RPC data."""


class RpcResponseError(RpcError):
    """Shelly returned an RPC error object."""

    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

