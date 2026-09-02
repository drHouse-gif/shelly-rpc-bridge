"""Direct Shelly Gen2+ outbound WebSocket bridge hosted by Home Assistant."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import secrets
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from aiohttp import WSMsgType, web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import MAX_DEVICES, WS_PATH
from .models import RemoteDevice

LOGGER = logging.getLogger(__name__)
RELAY_SRC = "srb_ha"
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")

DANGEROUS_METHODS = {
    "Shelly.FactoryReset",
    "Shelly.Reboot",
    "Shelly.ResetWiFiConfig",
    "Shelly.SetAuth",
    "Shelly.Update",
    "Shelly.PutUserCA",
    "Sys.SetConfig",
    "WiFi.SetConfig",
    "Eth.SetConfig",
    "Cloud.SetConfig",
    "MQTT.SetConfig",
    "WS.SetConfig",
}
DANGEROUS_PREFIXES = ("Script.", "Schedule.", "Webhook.")


class BridgeError(Exception):
    """Base bridge error."""


class BridgeUnavailable(BridgeError):
    """The target device is unavailable."""


def _is_dangerous_method(method: str) -> bool:
    return method in DANGEROUS_METHODS or method.startswith(DANGEROUS_PREFIXES)


def _infer_device_id(frame: dict[str, Any]) -> str | None:
    src = frame.get("src")
    if not isinstance(src, str) or src == RELAY_SRC or not DEVICE_ID_RE.fullmatch(src):
        return None
    return src


class BridgeServer:
    """Dispatch inbound Shelly WebSockets to the matching config entry."""

    def __init__(self) -> None:
        self._hubs: dict[str, BridgeHub] = {}

    def register(self, token: str, hub: BridgeHub) -> None:
        self._hubs[token] = hub

    def unregister(self, token: str, hub: BridgeHub) -> None:
        if self._hubs.get(token) is hub:
            self._hubs.pop(token, None)

    def hub_for_token(self, token: str) -> BridgeHub | None:
        if not token:
            return None
        for expected, hub in self._hubs.items():
            if hmac.compare_digest(token, expected):
                return hub
        return None


class BridgeReceiver(HomeAssistantView):
    """Accept outbound WebSocket connections from Shelly Gen2+ devices."""

    requires_auth = False
    url = WS_PATH
    name = "api:shelly_rpc_bridge:ws"

    def __init__(self, server: BridgeServer) -> None:
        self._server = server

    async def get(self, request: web.Request) -> web.WebSocketResponse | web.Response:
        token = request.query.get("token", "")
        hub = self._server.hub_for_token(token)
        if hub is None:
            return web.Response(status=401, text="Invalid bridge token")

        websocket = web.WebSocketResponse(heartbeat=20, max_msg_size=1_048_576)
        await websocket.prepare(request)
        await hub.async_handle_device(websocket)
        return websocket


class BridgeHub:
    """Maintain direct Shelly WebSocket sessions and remote device models."""

    def __init__(self, hass: HomeAssistant, token: str) -> None:
        self.hass = hass
        self.token = token
        self.devices: dict[str, RemoteDevice] = {}
        self.connected = False
        self._device_sockets: dict[str, web.WebSocketResponse] = {}
        self._request_id = secrets.randbelow(1_000_000) + 1
        self._pending: dict[tuple[str, int], asyncio.Future[dict[str, Any]]] = {}
        self._component_listeners: set[Callable[[RemoteDevice], None]] = set()
        self._update_listeners: dict[str, set[Callable[[], None]]] = defaultdict(set)
        self._bootstrap_tasks: dict[str, asyncio.Task[None]] = {}

    async def async_start(self) -> None:
        self.connected = True

    async def async_stop(self) -> None:
        self.connected = False
        for websocket in tuple(self._device_sockets.values()):
            await websocket.close(code=1001, message=b"Integration unloaded")
        self._device_sockets.clear()
        for task in self._bootstrap_tasks.values():
            task.cancel()
        self._bootstrap_tasks.clear()
        for future in self._pending.values():
            if not future.done():
                future.set_exception(BridgeUnavailable("Integration unloaded"))
        self._pending.clear()

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

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def async_handle_device(self, websocket: web.WebSocketResponse) -> None:
        device_id: str | None = None
        identify_id = self._next_request_id()
        await websocket.send_json(
            {"id": identify_id, "src": RELAY_SRC, "method": "Shelly.GetDeviceInfo"}
        )

        try:
            async for message in websocket:
                if message.type == WSMsgType.TEXT:
                    try:
                        frame = json.loads(message.data)
                    except json.JSONDecodeError:
                        continue
                elif message.type == WSMsgType.BINARY:
                    try:
                        frame = json.loads(message.data.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                    break
                else:
                    continue

                if not isinstance(frame, dict):
                    continue

                if device_id is None:
                    inferred = _infer_device_id(frame)
                    if inferred is None:
                        continue
                    if inferred not in self.devices and len(self.devices) >= MAX_DEVICES:
                        await websocket.close(code=4008, message=b"Device limit reached")
                        return
                    device_id = inferred
                    device = self.devices.setdefault(device_id, RemoteDevice(device_id))
                    old_socket = self._device_sockets.get(device_id)
                    if old_socket is not None and old_socket is not websocket:
                        await old_socket.close(code=4001, message=b"Replaced by reconnect")
                    self._device_sockets[device_id] = websocket
                    device.online = True
                    device.last_seen = time.time()
                    if frame.get("id") == identify_id and isinstance(frame.get("result"), dict):
                        device.info.update(frame["result"])
                    self._notify_update(device_id)
                    self._ensure_bootstrap(device_id)
                    LOGGER.info("Shelly %s connected directly to Home Assistant", device_id)

                device = self.devices[device_id]
                device.online = True
                device.last_seen = time.time()
                if frame.get("id") == identify_id and isinstance(frame.get("result"), dict):
                    device.info.update(frame["result"])
                self._handle_device_frame(device, frame)
        finally:
            if device_id is not None and self._device_sockets.get(device_id) is websocket:
                self._device_sockets.pop(device_id, None)
                device = self.devices[device_id]
                device.online = False
                device.last_seen = time.time()
                self._notify_update(device_id)
                LOGGER.info("Shelly %s disconnected", device_id)

    def _handle_device_frame(self, device: RemoteDevice, frame: dict[str, Any]) -> None:
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
                device.info.update(await self.async_rpc(device_id, "Shelly.GetDeviceInfo"))
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
                    components=[item for item in components if isinstance(item, dict)],
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
        if _is_dangerous_method(method):
            raise BridgeError(f"RPC method blocked: {method}")
        websocket = self._device_sockets.get(device_id)
        device = self.devices.get(device_id)
        if websocket is None or websocket.closed or device is None or not device.online:
            raise BridgeUnavailable("Device is offline")

        request_id = self._next_request_id()
        frame: dict[str, Any] = {
            "id": request_id,
            "src": RELAY_SRC,
            "method": method,
        }
        if params:
            frame["params"] = params
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[(device_id, request_id)] = future
        await websocket.send_json(frame)
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
        device = self.devices.get(device_id)
        if device is None or component_key not in device.components:
            return
        device.components[component_key].status.update(values)
        self._notify_update(device_id)
