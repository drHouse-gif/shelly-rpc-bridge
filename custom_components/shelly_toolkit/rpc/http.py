"""Shelly RPC over HTTP."""

from __future__ import annotations

import asyncio
from itertools import count
from typing import Any

import aiohttp

from .base import EventCallback, format_url_host, validate_method
from .errors import (
    RpcAuthError,
    RpcProtocolError,
    RpcResponseError,
    RpcTimeoutError,
    RpcUnavailableError,
)


class HttpRpcTransport:
    """Concurrent HTTP JSON-RPC transport with RFC 7616 digest auth."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        *,
        port: int = 80,
        username: str = "admin",
        password: str | None = None,
        use_ssl: bool = False,
        verify_ssl: bool = False,
        timeout: float = 12.0,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_ssl = use_ssl
        self._verify_ssl = verify_ssl
        self._timeout = timeout
        self._ids = count(1)
        self.connected = False
        self.last_error: str | None = None

    @property
    def url(self) -> str:
        """Return RPC endpoint."""
        scheme = "https" if self._use_ssl else "http"
        return f"{scheme}://{format_url_host(self._host)}:{self._port}/rpc"

    async def async_connect(self) -> None:
        """Validate transport with the unauthenticated device-info method."""
        await self.async_call("Shelly.GetDeviceInfo")

    async def async_call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Call a Shelly RPC method."""
        validate_method(method)
        request_id = next(self._ids)
        frame: dict[str, Any] = {
            "id": request_id,
            "src": "shelly_toolkit",
            "method": method,
        }
        if params is not None:
            frame["params"] = params
        request_kwargs: dict[str, Any] = {
            "json": frame,
            "timeout": aiohttp.ClientTimeout(total=self._timeout),
            "ssl": self._verify_ssl if self._use_ssl else None,
        }
        if self._password:
            request_kwargs["middlewares"] = (
                aiohttp.DigestAuthMiddleware(self._username, self._password),
            )
        try:
            async with self._session.post(self.url, **request_kwargs) as response:
                if response.status == 401:
                    raise RpcAuthError("Shelly authentication failed")
                if response.status >= 400:
                    raise RpcUnavailableError(f"HTTP RPC returned {response.status}")
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as err:
                    raise RpcProtocolError("Malformed JSON RPC response") from err
        except RpcAuthError:
            self.connected = False
            self.last_error = "authentication_failed"
            raise
        except asyncio.TimeoutError as err:
            self.connected = False
            self.last_error = "timeout"
            raise RpcTimeoutError(f"RPC {method} timed out") from err
        except aiohttp.ClientError as err:
            self.connected = False
            self.last_error = type(err).__name__
            raise RpcUnavailableError(f"Could not reach Shelly: {err}") from err
        if not isinstance(payload, dict):
            raise RpcProtocolError("RPC response must be a JSON object")
        if payload.get("id") != request_id:
            raise RpcProtocolError("RPC response ID does not match the request")
        if isinstance(error := payload.get("error"), dict):
            raise RpcResponseError(error.get("code"), str(error.get("message", error)))
        if "result" not in payload:
            raise RpcProtocolError("RPC response is missing result")
        result = payload["result"]
        self.connected = True
        self.last_error = None
        return result

    async def async_close(self) -> None:
        """Mark transport closed; the shared session is owned by Home Assistant."""
        self.connected = False

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """HTTP has no push notification channel."""
