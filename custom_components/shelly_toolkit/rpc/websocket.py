"""Shelly RPC over a client WebSocket connection."""

from __future__ import annotations

import asyncio
import hashlib
import json
from itertools import count
import secrets
from typing import Any

import aiohttp

from .base import EventCallback, validate_method
from .errors import (
    RpcAuthError,
    RpcProtocolError,
    RpcResponseError,
    RpcTimeoutError,
    RpcUnavailableError,
)


class WebSocketRpcTransport:
    """Concurrent, reconnecting Shelly WebSocket RPC transport."""

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
        self._ids = count(secrets.randbelow(1_000_000) + 1)
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task[None] | None = None
        self._connect_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._event_callback: EventCallback | None = None
        self._challenge: dict[str, Any] | None = None
        self._nonce_count = 0
        self.connected = False
        self.last_error: str | None = None

    @property
    def url(self) -> str:
        """Return WebSocket RPC endpoint."""
        scheme = "wss" if self._use_ssl else "ws"
        return f"{scheme}://{self._host}:{self._port}/rpc"

    async def async_connect(self) -> None:
        """Connect once; concurrent callers share the same attempt."""
        if self._socket is not None and not self._socket.closed and self.connected:
            return
        async with self._connect_lock:
            if self._socket is not None and not self._socket.closed and self.connected:
                return
            await self._close_socket()
            try:
                self._socket = await self._session.ws_connect(
                    self.url,
                    heartbeat=20,
                    timeout=aiohttp.ClientWSTimeout(ws_receive=None, ws_close=5),
                    ssl=self._verify_ssl if self._use_ssl else None,
                    max_msg_size=1_048_576,
                )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                self.last_error = type(err).__name__
                raise RpcUnavailableError(f"Could not connect Shelly WebSocket: {err}") from err
            self.connected = True
            self.last_error = None
            self._reader = asyncio.create_task(self._reader_loop())

    async def async_call(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call an RPC method, reconnecting once after transport failure."""
        validate_method(method)
        for attempt in range(2):
            try:
                await self.async_connect()
                return await self._call_connected(method, params)
            except RpcResponseError as err:
                if err.code != 401 or attempt:
                    raise
                self._set_challenge(err.message)
            except RpcUnavailableError:
                if attempt:
                    raise
                await self._close_socket()
        raise RpcUnavailableError("RPC call failed")

    async def _call_connected(
        self, method: str, params: dict[str, Any] | None
    ) -> dict[str, Any]:
        socket = self._socket
        if socket is None or socket.closed:
            raise RpcUnavailableError("WebSocket is not connected")
        request_id = next(self._ids)
        frame: dict[str, Any] = {
            "id": request_id,
            "src": "shelly_toolkit",
            "method": method,
        }
        if params is not None:
            frame["params"] = params
        if self._challenge is not None:
            frame["auth"] = self._build_auth()
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await socket.send_json(frame)
            async with asyncio.timeout(self._timeout):
                return await future
        except asyncio.TimeoutError as err:
            self.last_error = "timeout"
            raise RpcTimeoutError(f"RPC {method} timed out") from err
        except (aiohttp.ClientError, ConnectionError) as err:
            self.connected = False
            self.last_error = type(err).__name__
            raise RpcUnavailableError(f"WebSocket send failed: {err}") from err
        finally:
            self._pending.pop(request_id, None)

    async def _reader_loop(self) -> None:
        socket = self._socket
        if socket is None:
            return
        try:
            async for message in socket:
                if message.type not in {aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY}:
                    if message.type in {
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    }:
                        break
                    continue
                try:
                    raw = message.data.decode() if isinstance(message.data, bytes) else message.data
                    frame = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.last_error = "malformed_json"
                    continue
                if not isinstance(frame, dict):
                    continue
                request_id = frame.get("id")
                if isinstance(request_id, int) and request_id in self._pending:
                    future = self._pending[request_id]
                    if isinstance(error := frame.get("error"), dict):
                        future.set_exception(
                            RpcResponseError(
                                error.get("code"), str(error.get("message", error))
                            )
                        )
                    elif isinstance(result := frame.get("result"), dict):
                        future.set_result(result)
                    else:
                        future.set_exception(RpcProtocolError("Malformed RPC response"))
                    continue
                if isinstance(frame.get("method"), str) and self._event_callback is not None:
                    callback_result = self._event_callback(frame)
                    if asyncio.iscoroutine(callback_result):
                        await callback_result
        finally:
            self.connected = False
            for future in tuple(self._pending.values()):
                if not future.done():
                    future.set_exception(RpcUnavailableError("WebSocket disconnected"))

    def _set_challenge(self, message: str) -> None:
        if not self._password:
            raise RpcAuthError("Shelly requires authentication")
        try:
            challenge = json.loads(message)
        except json.JSONDecodeError as err:
            raise RpcAuthError("Malformed Shelly authentication challenge") from err
        if not isinstance(challenge, dict) or not challenge.get("nonce") or not challenge.get("realm"):
            raise RpcAuthError("Incomplete Shelly authentication challenge")
        self._challenge = challenge
        self._nonce_count = 0

    def _build_auth(self) -> dict[str, Any]:
        assert self._challenge is not None and self._password is not None
        self._nonce_count += 1
        realm = str(self._challenge["realm"])
        nonce = self._challenge["nonce"]
        nc = f"{self._nonce_count:08x}"
        cnonce = secrets.randbelow(2_147_483_647)
        ha1 = hashlib.sha256(
            f"{self._username}:{realm}:{self._password}".encode()
        ).hexdigest()
        ha2 = hashlib.sha256(b"dummy_method:dummy_uri").hexdigest()
        response = hashlib.sha256(
            f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}".encode()
        ).hexdigest()
        return {
            "realm": realm,
            "username": self._username,
            "nonce": nonce,
            "cnonce": cnonce,
            "nc": nc,
            "response": response,
            "algorithm": "SHA-256",
        }

    async def _close_socket(self) -> None:
        reader, self._reader = self._reader, None
        socket, self._socket = self._socket, None
        current = asyncio.current_task()
        if reader is not None and reader is not current:
            reader.cancel()
            try:
                await reader
            except asyncio.CancelledError:
                pass
        if socket is not None and not socket.closed:
            await socket.close()
        self.connected = False

    async def async_close(self) -> None:
        """Close WebSocket and fail pending calls."""
        await self._close_socket()
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(RpcUnavailableError("Transport closed"))
        self._pending.clear()

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Set notification callback."""
        self._event_callback = callback

