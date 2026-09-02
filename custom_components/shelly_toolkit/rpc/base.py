"""RPC transport protocol and shared validation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import re
from typing import Any, Protocol

from .errors import RpcProtocolError

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
METHOD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$")


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

    async def async_call(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call an RPC method."""

    async def async_close(self) -> None:
        """Close the transport."""

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Set notification callback."""

