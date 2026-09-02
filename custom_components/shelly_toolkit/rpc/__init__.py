"""Unified Shelly RPC transport layer."""

from .base import EventCallback, RpcTransport, validate_method
from .errors import (
    RpcAuthError,
    RpcError,
    RpcProtocolError,
    RpcResponseError,
    RpcTimeoutError,
    RpcUnavailableError,
)
from .http import HttpRpcTransport
from .websocket import WebSocketRpcTransport

__all__ = [
    "EventCallback",
    "HttpRpcTransport",
    "RpcAuthError",
    "RpcError",
    "RpcProtocolError",
    "RpcResponseError",
    "RpcTimeoutError",
    "RpcTransport",
    "RpcUnavailableError",
    "WebSocketRpcTransport",
    "validate_method",
]

