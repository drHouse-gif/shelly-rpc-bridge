"""Authenticated inbound WebSocket support for remote Shelly devices."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Iterable
from itertools import count
from typing import Any

from aiohttp import WSMsgType, web
from homeassistant.components.http import HomeAssistantView

from .const import MAX_DEVICES, REMOTE_WS_PATH
from .rpc import (
    EventCallback,
    RpcProtocolError,
    RpcResponseError,
    RpcTimeoutError,
    RpcUnavailableError,
    validate_method,
)

LOGGER = logging.getLogger(__name__)
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")
BindCallback = Callable[[str, str], Awaitable[None]]
ConnectCallback = Callable[[str, dict[str, Any], "RemoteRpcTransport"], Awaitable[None]]
DisconnectCallback = Callable[[str], Awaitable[None]]


def hash_remote_secret(secret: str) -> str:
    """Hash a high-entropy remote bearer secret for storage."""
    return hashlib.sha256(secret.encode()).hexdigest()


def new_remote_credential(name: str) -> tuple[dict[str, Any], str]:
    """Create a stored credential record and one-time plaintext secret."""
    secret = secrets.token_urlsafe(48)
    record = {
        "id": secrets.token_hex(8),
        "name": name.strip() or "Remote Shelly",
        "secret_hash": hash_remote_secret(secret),
        "created_at": time.time(),
        "bound_device_id": None,
    }
    return record, secret


def normalize_credentials(raw: Iterable[Any]) -> list[dict[str, Any]]:
    """Validate records and migrate legacy plaintext token records in memory."""
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        credential_id = item.get("id")
        name = item.get("name")
        if not isinstance(credential_id, str) or not isinstance(name, str):
            continue
        secret_hash = item.get("secret_hash")
        legacy = item.get("token")
        if not isinstance(secret_hash, str) and isinstance(legacy, str):
            secret_hash = hash_remote_secret(legacy)
        if not isinstance(secret_hash, str) or len(secret_hash) != 64:
            continue
        bound = item.get("bound_device_id")
        result.append(
            {
                "id": credential_id,
                "name": name,
                "secret_hash": secret_hash,
                "created_at": float(item.get("created_at", time.time())),
                "bound_device_id": bound if isinstance(bound, str) else None,
            }
        )
    return result


class RemoteRpcTransport:
    """RPC transport over a Shelly-initiated WebSocket."""

    def __init__(self, socket: web.WebSocketResponse, device_id: str) -> None:
        self._socket = socket
        self.device_id = device_id
        self._ids = count(secrets.randbelow(1_000_000) + 1)
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._event_callback: EventCallback | None = None
        self.connected = True
        self.last_error: str | None = None

    async def async_connect(self) -> None:
        """Validate current connection."""
        if self._socket.closed or not self.connected:
            raise RpcUnavailableError("Remote Shelly is offline")

    async def async_call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Call RPC over the established outbound socket."""
        validate_method(method)
        await self.async_connect()
        request_id = next(self._ids)
        frame: dict[str, Any] = {
            "id": request_id,
            "src": "shelly_toolkit",
            "method": method,
        }
        if params is not None:
            frame["params"] = params
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._socket.send_json(frame)
            async with asyncio.timeout(12):
                return await future
        except asyncio.TimeoutError as err:
            self.last_error = "timeout"
            raise RpcTimeoutError(f"Remote RPC {method} timed out") from err
        except (ConnectionError, RuntimeError) as err:
            self.connected = False
            self.last_error = type(err).__name__
            raise RpcUnavailableError("Remote WebSocket disconnected") from err
        finally:
            self._pending.pop(request_id, None)

    async def async_handle_frame(self, frame: dict[str, Any]) -> None:
        """Resolve replies and forward notifications."""
        request_id = frame.get("id")
        if isinstance(request_id, int) and request_id in self._pending:
            future = self._pending[request_id]
            if isinstance(error := frame.get("error"), dict):
                future.set_exception(
                    RpcResponseError(error.get("code"), str(error.get("message", error)))
                )
            elif "result" in frame:
                future.set_result(frame["result"])
            else:
                future.set_exception(RpcProtocolError("Malformed remote RPC response"))
            return
        if isinstance(frame.get("method"), str) and self._event_callback is not None:
            callback_result = self._event_callback(frame)
            if asyncio.iscoroutine(callback_result):
                await callback_result

    async def async_close(self) -> None:
        """Close and fail pending calls."""
        self.connected = False
        if not self._socket.closed:
            await self._socket.close(code=1001, message=b"Toolkit closing")
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(RpcUnavailableError("Remote transport closed"))
        self._pending.clear()

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Set notification callback."""
        self._event_callback = callback


class RemoteServer:
    """Validate credentials and dispatch Shelly-initiated sockets."""

    def __init__(self) -> None:
        self._credentials: dict[str, dict[str, Any]] = {}
        self._transports: dict[str, RemoteRpcTransport] = {}
        self._credential_devices: dict[str, str] = {}
        self._bind_callback: BindCallback | None = None
        self._connect_callback: ConnectCallback | None = None
        self._disconnect_callback: DisconnectCallback | None = None

    def configure(
        self,
        credentials: Iterable[dict[str, Any]],
        *,
        bind_callback: BindCallback,
        connect_callback: ConnectCallback,
        disconnect_callback: DisconnectCallback,
    ) -> None:
        """Replace credential set and callbacks."""
        self._credentials = {item["id"]: dict(item) for item in credentials}
        self._bind_callback = bind_callback
        self._connect_callback = connect_callback
        self._disconnect_callback = disconnect_callback

    async def async_update_credentials(self, credentials: Iterable[dict[str, Any]]) -> None:
        """Replace credentials and disconnect revoked or regenerated sessions."""
        updated = {item["id"]: dict(item) for item in credentials}
        for credential_id, device_id in tuple(self._credential_devices.items()):
            old = self._credentials.get(credential_id)
            new = updated.get(credential_id)
            if (
                old is not None
                and new is not None
                and hmac.compare_digest(str(old["secret_hash"]), str(new["secret_hash"]))
            ):
                continue
            transport = self._transports.get(device_id)
            if transport is not None:
                await transport.async_close()
        self._credentials = updated

    def authenticate(self, credential_id: str, secret: str) -> bool:
        """Constant-time validate a high-entropy bearer secret."""
        record = self._credentials.get(credential_id)
        if record is None or not secret:
            return False
        return hmac.compare_digest(str(record["secret_hash"]), hash_remote_secret(secret))

    async def async_handle(self, socket: web.WebSocketResponse, credential_id: str) -> None:
        """Identify, bind, and serve one outbound Shelly socket."""
        identify_id = secrets.randbelow(1_000_000) + 1
        await socket.send_json(
            {"id": identify_id, "src": "shelly_toolkit", "method": "Shelly.GetDeviceInfo"}
        )
        device_id: str | None = None
        transport: RemoteRpcTransport | None = None
        try:
            async for message in socket:
                frame = self._decode_message(message)
                if frame is None:
                    continue
                if device_id is None:
                    source = frame.get("src")
                    if not isinstance(source, str) or not DEVICE_ID_RE.fullmatch(source):
                        continue
                    if len(self._transports) >= MAX_DEVICES and source not in self._transports:
                        await socket.close(code=4008, message=b"Device limit reached")
                        return
                    record = self._credentials.get(credential_id)
                    if record is None:
                        await socket.close(code=4003, message=b"Credential revoked")
                        return
                    bound = record.get("bound_device_id")
                    if isinstance(bound, str) and bound != source:
                        await socket.close(code=4003, message=b"Credential bound to another device")
                        return
                    if bound is None:
                        record["bound_device_id"] = source
                        if self._bind_callback is not None:
                            await self._bind_callback(credential_id, source)
                    device_id = source
                    existing_device = self._credential_devices.get(credential_id)
                    if existing_device is not None and existing_device != device_id:
                        await socket.close(code=4003, message=b"Credential already in use")
                        return
                    old = self._transports.get(device_id)
                    if old is not None:
                        await old.async_close()
                    transport = RemoteRpcTransport(socket, device_id)
                    self._transports[device_id] = transport
                    self._credential_devices[credential_id] = device_id
                    info = frame.get("result") if frame.get("id") == identify_id else {}
                    if not isinstance(info, dict):
                        info = {}
                    if self._connect_callback is not None:
                        await self._connect_callback(device_id, info, transport)
                    LOGGER.info("Remote Shelly %s connected", device_id)
                assert transport is not None
                await transport.async_handle_frame(frame)
        finally:
            if device_id is not None and self._transports.get(device_id) is transport:
                self._transports.pop(device_id, None)
                if self._credential_devices.get(credential_id) == device_id:
                    self._credential_devices.pop(credential_id, None)
                if transport is not None:
                    transport.connected = False
                if self._disconnect_callback is not None:
                    await self._disconnect_callback(device_id)
                LOGGER.info("Remote Shelly %s disconnected", device_id)

    @staticmethod
    def _decode_message(message: Any) -> dict[str, Any] | None:
        if message.type == WSMsgType.TEXT:
            raw = message.data
        elif message.type == WSMsgType.BINARY:
            try:
                raw = message.data.decode()
            except UnicodeDecodeError:
                return None
        else:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    async def async_close(self) -> None:
        """Close every remote transport."""
        for transport in tuple(self._transports.values()):
            await transport.async_close()
        self._transports.clear()
        self._credential_devices.clear()


class RemoteReceiverView(HomeAssistantView):
    """Unauthenticated HA endpoint protected by Toolkit bearer credentials."""

    requires_auth = False
    url = REMOTE_WS_PATH
    name = "api:shelly_toolkit:remote"

    def __init__(self, server: RemoteServer) -> None:
        self._server = server

    async def get(self, request: web.Request) -> web.WebSocketResponse | web.Response:
        """Validate before upgrading to a WebSocket."""
        credential_id = request.query.get("id", "")
        secret = request.query.get("token", "")
        if not self._server.authenticate(credential_id, secret):
            return web.Response(status=401, text="Invalid remote credential")
        socket = web.WebSocketResponse(heartbeat=20, max_msg_size=1_048_576)
        await socket.prepare(request)
        await self._server.async_handle(socket, credential_id)
        return socket
