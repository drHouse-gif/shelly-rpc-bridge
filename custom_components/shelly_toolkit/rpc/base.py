"""RPC transport protocol and shared validation."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from .errors import RpcProtocolError

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
METHOD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$")


def format_url_host(host: str) -> str:
    """Wrap a literal IPv6 host for URL use without changing DNS names."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def validate_method(method: str) -> str:
    """Validate an RPC method name."""
    if not METHOD_RE.fullmatch(method):
        raise RpcProtocolError(f"Invalid RPC method: {method!r}")
    return method


class RpcTransport(Protocol):
    """Transport-independent Shelly RPC interface."""

    connected: bool
    last_error: str | None

    async def async_connect(self) -> None:
        """Connect or validate the transport."""

    async def async_call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Call an RPC method."""

    async def async_close(self) -> None:
        """Close the transport."""

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Set notification callback."""
