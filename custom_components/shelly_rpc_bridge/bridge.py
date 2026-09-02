"""WebSocket client used by the Home Assistant integration."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from aiohttp import ClientError, WSMsgType

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_RELAY_PATH, PROTOCOL_VERSION
from .models import RemoteDevice

LOGGER = logging.getLogger(__name__)


class BridgeError(Exception):
    """Base bridge error."""


class BridgeAuthError(BridgeError):
    """Authentication was rejected."""


class BridgeProtocolError(BridgeError):
    """The server didn't speak the expected bridge protocol."""


class BridgeUnavailable(BridgeError):
    """The relay or target device is unavailable."""


def normalize_relay_url(value: str) -> str:
    """Normalize a relay base URL to its HA WebSocket endpoint."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        raise ValueError("Relay URL must start with ws:// or wss://")
    path = parsed.path.rstrip("/")
    if not path:
        path = DEFAULT_RELAY_PATH
    if path != DEFAULT_RELAY_PATH:
        raise ValueError("Relay URL path must be /ha")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


async def async_validate_connection(
    hass: HomeAssistant, relay_url: str, token: str
) -> str:
    """Open one short connection and return the non-secret site id."""
    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(12):
            websocket = await session.ws_connect(
                normalize_relay_url(relay_url),
                params={"token": token},
                heartbeat=20,
                max_msg_size=1_048_576,
            )
            try:
                ws_message = await websocket.receive()
                if ws_message.type == WSMsgType.TEXT:
                    message = json.loads(ws_message.data)
                elif websocket.close_code == 4003:
                    raise BridgeAuthError("Invalid Home Assistant token")
                else:
                    raise BridgeProtocolError("Relay closed before hello")
            finally:
                await websocket.close()
    except asyncio.TimeoutError as err:
        raise BridgeUnavailable("Relay connection timed out") from err
    except json.JSONDecodeError as err:
        raise BridgeProtocolError("Relay hello isn't valid JSON") from err
    except ClientError as err:
        raise BridgeUnavailable(str(err)) from err

    if not isinstance(message, dict) or message.get("bridge") != "hello":
        raise BridgeProtocolError("Relay didn't send a bridge hello")
    if message.get("protocol") != PROTOCOL_VERSION:
        raise BridgeProtocolError("Unsupported relay protocol version")
    site_id = message.get("site_id")
    if not isinstance(site_id, str) or not site_id:
        raise BridgeProtocolError("Relay didn't provide a site id")
    return site_id


class BridgeHub:
    """Maintain the relay connection and all remote device models."""

    def __init__(self, hass: HomeAssistant, relay_url: str, token: str) -> None:
        self.hass = hass
        self.relay_url = normalize_relay_url(relay_url)
        self.token = token
        self.devices: dict[str, RemoteDevice] = {}
        self.connected = False
        self.site_id: str | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._websocket: Any = None
        self._request_id = secrets.randbelow(1_000_000) + 1
        self._source = f"ha_srb_{secrets.token_hex(6)}"
        self._pending: dict[tuple[str, int], asyncio.Future[dict[str, Any]]] = {}
        self._component_listeners: set[Callable[[RemoteDevice], None]] = set()
        self._update_listeners: dict[str, set[Callable[[], None]]] = defaultdict(set)
        self._bootstrap_tasks: dict[str, asyncio.Task[None]] = {}

    async def async_start(self) -> None:
        self._running = True
        self._task = self.hass.async_create_task(
            self._run(), "Shelly RPC Bridge connection"
        )

    async def async_stop(self) -> None:
        self._running = False
        if self._websocket is not None:
            await self._websocket.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for task in self._bootstrap_tasks.values():
            task.cancel()
        self._bootstrap_tasks.clear()

    def async_add_component_listener(
        self, callback: Callable[[RemoteDevice], None]
    ) -> Callable[[], None]:
        self._component_listeners.add(callback)
        for device in self.devices.values():
            if device.components:
                callback(device)
        return lambda: self._component_listeners.discard(callback)

    def async_add_update_listener(
        self, device_id: str, callback: Callable[[], None]
    ) -> Callable[[], None]:
        self._update_listeners[device_id].add(callback)

        def remove() -> None:
            self._update_listeners[device_id].discard(callback)

        return remove

    def _notify_components(self, device: RemoteDevice) -> None:
        for callback in tuple(self._component_listeners):
            callback(device)

    def _notify_update(self, device_id: str) -> None:
        for callback in tuple(self._update_listeners[device_id]):
            callback()

    async def _run(self) -> None:
        delay = 1
        session = async_get_clientsession(self.hass)
        while self._running:
            try:
                websocket = await session.ws_connect(
                    self.relay_url,
                    params={"token": self.token},
                    heartbeat=20,
                    max_msg_size=1_048_576,
                )
                self._websocket = websocket
                delay = 1
                async for message in websocket:
                    if message.type == WSMsgType.TEXT:
                        try:
                            envelope = message.json()
                        except ValueError:
                            continue
                        if isinstance(envelope, dict):
                            await self._handle_envelope(envelope)
                    elif message.type in {WSMsgType.CLOSED, WSMsgType.ERROR}:
                        break
            except (ClientError, asyncio.TimeoutError) as err:
                LOGGER.warning("Relay connection failed: %s", err)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Unexpected relay connection error")
            finally:
                self.connected = False
                self._websocket = None
                for device in self.devices.values():
                    device.online = False
                    self._notify_update(device.device_id)
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(BridgeUnavailable("Relay disconnected"))
                self._pending.clear()

            if self._running:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def _handle_envelope(self, envelope: dict[str, Any]) -> None:
        kind = envelope.get("bridge")
        if kind == "error":
            device_id = envelope.get("device_id")
            request_id = envelope.get("request_id")
            if isinstance(device_id, str) and isinstance(request_id, int):
                future = self._pending.pop((device_id, request_id), None)
                if future is not None and not future.done():
                    future.set_exception(
                        BridgeError(str(envelope.get("code", "relay_error")))
                    )
            return
        if kind == "hello":
            if envelope.get("protocol") != PROTOCOL_VERSION:
                raise BridgeProtocolError("Unsupported relay protocol")
            self.site_id = envelope.get("site_id")
            self.connected = True
            for item in envelope.get("devices", []):
                if not isinstance(item, dict):
                    continue
                device_id = item.get("device_id")
                if not isinstance(device_id, str):
                    continue
                device = self.devices.setdefault(device_id, RemoteDevice(device_id))
                device.online = bool(item.get("online"))
                device.last_seen = item.get("last_seen")
                self._notify_update(device_id)
            return

        device_id = envelope.get("device_id")
        if not isinstance(device_id, str):
            return
        device = self.devices.setdefault(device_id, RemoteDevice(device_id))
        if isinstance(envelope.get("last_seen"), (int, float)):
            device.last_seen = float(envelope["last_seen"])

        if kind == "device_online":
            device.online = True
            self._notify_update(device_id)
            self._ensure_bootstrap(device_id)
            return
        if kind == "device_offline":
            device.online = False
            self._notify_update(device_id)
            return
        if kind == "device_snapshot":
            raw_info = envelope.get("info")
            raw_components = envelope.get("components")
            device.apply_snapshot(
                online=bool(envelope.get("online")),
                last_seen=device.last_seen,
                info=raw_info if isinstance(raw_info, dict) else {},
                components=(
                    [x for x in raw_components if isinstance(x, dict)]
                    if isinstance(raw_components, list)
                    else []
                ),
            )
            self._notify_components(device)
            self._notify_update(device_id)
            return
        if kind == "device_message":
            frame = envelope.get("frame")
            if isinstance(frame, dict):
                self._handle_device_frame(device, frame)

    def _handle_device_frame(
        self, device: RemoteDevice, frame: dict[str, Any]
    ) -> None:
        response_id = frame.get("id")
        if isinstance(response_id, int) and "method" not in frame:
            future = self._pending.pop((device.device_id, response_id), None)
            if future is not None and not future.done():
                error = frame.get("error")
                if isinstance(error, dict):
                    future.set_exception(BridgeError(str(error.get("message", error))))
                else:
                    result = frame.get("result")
                    future.set_result(result if isinstance(result, dict) else {})
        if device.apply_rpc_frame(frame):
            self._notify_components(device)
            self._notify_update(device.device_id)

    def _ensure_bootstrap(self, device_id: str) -> None:
        existing = self._bootstrap_tasks.get(device_id)
        if existing is not None and not existing.done():
            return
        self._bootstrap_tasks[device_id] = self.hass.async_create_task(
            self._bootstrap(device_id), f"Bootstrap remote Shelly {device_id}"
        )

    async def _bootstrap(self, device_id: str) -> None:
        device = self.devices[device_id]
        try:
            if not device.info:
                device.info.update(
                    await self.async_rpc(device_id, "Shelly.GetDeviceInfo")
                )
            result = await self.async_rpc(
                device_id,
                "Shelly.GetComponents",
                {"include": ["config", "status"]},
            )
            components = result.get("components")
            if isinstance(components, list):
                device.apply_snapshot(
                    online=True,
                    last_seen=device.last_seen,
                    info={},
                    components=[x for x in components if isinstance(x, dict)],
                )
                self._notify_components(device)
                self._notify_update(device_id)
        except BridgeError as err:
            LOGGER.debug("Could not bootstrap %s: %s", device_id, err)
        finally:
            self._bootstrap_tasks.pop(device_id, None)

    async def async_rpc(
        self,
        device_id: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        websocket = self._websocket
        if websocket is None or websocket.closed:
            raise BridgeUnavailable("Relay is disconnected")
        device = self.devices.get(device_id)
        if device is None or not device.online:
            raise BridgeUnavailable("Device is offline")

        self._request_id += 1
        request_id = self._request_id
        frame: dict[str, Any] = {
            "id": request_id,
            "src": self._source,
            "method": method,
        }
        if params:
            frame["params"] = params
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[(device_id, request_id)] = future
        await websocket.send_json(
            {"bridge": "rpc", "device_id": device_id, "frame": frame}
        )
        try:
            async with asyncio.timeout(12):
                return await future
        except asyncio.TimeoutError as err:
            raise BridgeUnavailable(f"RPC {method} timed out") from err
        finally:
            self._pending.pop((device_id, request_id), None)

    def set_component_status(
        self, device_id: str, component_key: str, values: dict[str, Any]
    ) -> None:
        """Apply optimistic UI state after an accepted control command."""
        device = self.devices.get(device_id)
        if device is None or component_key not in device.components:
            return
        device.components[component_key].status.update(values)
        self._notify_update(device_id)
