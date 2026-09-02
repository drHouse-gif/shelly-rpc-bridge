"""Multi-site WebSocket relay for Shelly Gen2+ RPC devices.

Shelly devices connect to /device with a device token. Home Assistant clients
connect to /ha with a different token. Shelly frames stay untouched on the
device side and are wrapped with a device id on the HA side.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import signal
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

LOGGER = logging.getLogger("shelly_rpc_bridge.relay")

PROTOCOL_VERSION = 1
RELAY_SRC = "srb_relay"
MAX_DEVICES_PER_SITE = int(os.getenv("BRIDGE_MAX_DEVICES_PER_SITE", "500"))
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")

# These methods can disconnect, reconfigure, update, or erase a remote device.
# The HA integration doesn't need them. Set BRIDGE_ALLOW_DANGEROUS_RPC=true only
# for a trusted development environment.
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


@dataclass(slots=True, frozen=True)
class SiteCredentials:
    """Credentials for one logical Home Assistant site."""

    site_id: str
    device_token: str
    ha_token: str


@dataclass(slots=True)
class DeviceRecord:
    """Last known state for a device, retained while it sleeps or reconnects."""

    device_id: str
    connection: ServerConnection | None = None
    info: dict[str, Any] = field(default_factory=dict)
    components: list[dict[str, Any]] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)

    @property
    def online(self) -> bool:
        return self.connection is not None


@dataclass(slots=True)
class SiteState:
    """Runtime connections and cached device metadata for one site."""

    credentials: SiteCredentials
    controllers: set[ServerConnection] = field(default_factory=set)
    devices: dict[str, DeviceRecord] = field(default_factory=dict)


class BridgeRelay:
    """Route WebSocket messages between Shelly devices and HA controllers."""

    def __init__(self, sites: list[SiteCredentials]) -> None:
        if not sites:
            raise ValueError("At least one site must be configured")
        self.sites = {site.site_id: SiteState(site) for site in sites}
        self.allow_dangerous_rpc = _env_bool("BRIDGE_ALLOW_DANGEROUS_RPC", False)

    async def process_request(self, connection: ServerConnection, request: Any) -> Any:
        """Serve a small health endpoint without another HTTP server."""
        if urlsplit(request.path).path == "/healthz":
            return connection.respond(HTTPStatus.OK, "ok\n")
        return None

    async def handle_connection(self, websocket: ServerConnection) -> None:
        """Authenticate and dispatch a new WebSocket connection."""
        parsed = urlsplit(websocket.request.path)
        token = parse_qs(parsed.query).get("token", [""])[0]

        if parsed.path == "/device":
            site = self._site_for_token(token, role="device")
            if site is None:
                await websocket.close(code=4003, reason="Invalid device token")
                return
            await self._handle_device(websocket, site)
            return

        if parsed.path == "/ha":
            site = self._site_for_token(token, role="ha")
            if site is None:
                await websocket.close(code=4003, reason="Invalid HA token")
                return
            await self._handle_controller(websocket, site)
            return

        await websocket.close(code=4004, reason="Use /device or /ha")

    def _site_for_token(self, token: str, role: str) -> SiteState | None:
        if not token:
            return None
        for site in self.sites.values():
            expected = (
                site.credentials.device_token
                if role == "device"
                else site.credentials.ha_token
            )
            if hmac.compare_digest(token, expected):
                return site
        return None

    async def _handle_controller(
        self, websocket: ServerConnection, site: SiteState
    ) -> None:
        site.controllers.add(websocket)
        LOGGER.info("HA connected to site %s", site.credentials.site_id)
        try:
            await websocket.send(
                json.dumps(
                    {
                        "bridge": "hello",
                        "protocol": PROTOCOL_VERSION,
                        "site_id": site.credentials.site_id,
                        "devices": [
                            {
                                "device_id": record.device_id,
                                "online": record.online,
                                "last_seen": record.last_seen,
                            }
                            for record in site.devices.values()
                        ],
                    }
                )
            )
            for record in site.devices.values():
                await self._send_snapshot(websocket, record)

            async for raw in websocket:
                message = _decode_json(raw)
                if message is None:
                    await self._send_error(websocket, "invalid_json")
                    continue
                await self._handle_controller_message(websocket, site, message)
        except ConnectionClosed:
            pass
        finally:
            site.controllers.discard(websocket)
            LOGGER.info("HA disconnected from site %s", site.credentials.site_id)

    async def _handle_controller_message(
        self,
        websocket: ServerConnection,
        site: SiteState,
        message: dict[str, Any],
    ) -> None:
        kind = message.get("bridge")
        if kind == "list":
            await websocket.send(
                json.dumps(
                    {
                        "bridge": "devices",
                        "devices": [
                            {
                                "device_id": record.device_id,
                                "online": record.online,
                                "last_seen": record.last_seen,
                            }
                            for record in site.devices.values()
                        ],
                    }
                )
            )
            return

        if kind != "rpc":
            await self._send_error(websocket, "unknown_bridge_message")
            return

        device_id = message.get("device_id")
        frame = message.get("frame")
        if not isinstance(device_id, str) or not isinstance(frame, dict):
            await self._send_error(websocket, "invalid_rpc_envelope")
            return

        method = frame.get("method")
        if not isinstance(method, str):
            await self._send_error(
                websocket, "missing_rpc_method", device_id, frame.get("id")
            )
            return
        if not self.allow_dangerous_rpc and _is_dangerous_method(method):
            await self._send_error(
                websocket, "rpc_method_blocked", device_id, frame.get("id")
            )
            return

        record = site.devices.get(device_id)
        if record is None or record.connection is None:
            await self._send_error(
                websocket, "device_offline", device_id, frame.get("id")
            )
            return

        try:
            await record.connection.send(json.dumps(frame))
        except ConnectionClosed:
            await self._send_error(
                websocket, "device_offline", device_id, frame.get("id")
            )

    async def _handle_device(
        self, websocket: ServerConnection, site: SiteState
    ) -> None:
        device_id: str | None = None
        identify_id = secrets.randbelow(2_000_000_000) + 1
        components_id = secrets.randbelow(2_000_000_000) + 1
        identify_request = {
            "id": identify_id,
            "src": RELAY_SRC,
            "method": "Shelly.GetDeviceInfo",
        }
        await websocket.send(json.dumps(identify_request))

        try:
            async for raw in websocket:
                frame = _decode_json(raw)
                if frame is None:
                    continue

                inferred = _infer_device_id(frame)
                if inferred is not None and device_id is None:
                    device_id = inferred
                    if (
                        device_id not in site.devices
                        and len(site.devices) >= MAX_DEVICES_PER_SITE
                    ):
                        await websocket.close(code=4008, reason="Site device limit reached")
                        return

                    record = site.devices.get(device_id)
                    if record is None:
                        record = DeviceRecord(device_id=device_id)
                        site.devices[device_id] = record
                    if record.connection is not None and record.connection is not websocket:
                        await record.connection.close(code=4001, reason="Replaced by reconnect")
                    record.connection = websocket
                    record.last_seen = time.time()

                    if frame.get("id") == identify_id and isinstance(
                        frame.get("result"), dict
                    ):
                        record.info = frame["result"]

                    await self._broadcast(
                        site,
                        {
                            "bridge": "device_online",
                            "device_id": device_id,
                            "last_seen": record.last_seen,
                        },
                    )
                    await websocket.send(
                        json.dumps(
                            {
                                "id": components_id,
                                "src": RELAY_SRC,
                                "method": "Shelly.GetComponents",
                                "params": {"include": ["config", "status"]},
                            }
                        )
                    )
                    LOGGER.info(
                        "Device %s connected to site %s",
                        device_id,
                        site.credentials.site_id,
                    )

                if device_id is None:
                    # A well-behaved device response contains src. Don't route an
                    # unauthenticated identity into the controller namespace.
                    continue

                record = site.devices[device_id]
                record.last_seen = time.time()
                if frame.get("id") == identify_id and isinstance(
                    frame.get("result"), dict
                ):
                    record.info = frame["result"]
                if frame.get("id") == components_id and isinstance(
                    frame.get("result"), dict
                ):
                    components = frame["result"].get("components")
                    if isinstance(components, list):
                        record.components = [x for x in components if isinstance(x, dict)]
                    await self._broadcast_snapshot(site, record)

                await self._broadcast(
                    site,
                    {
                        "bridge": "device_message",
                        "device_id": device_id,
                        "frame": frame,
                        "last_seen": record.last_seen,
                    },
                )
        except ConnectionClosed:
            pass
        finally:
            if device_id is not None:
                record = site.devices.get(device_id)
                if record is not None and record.connection is websocket:
                    record.connection = None
                    record.last_seen = time.time()
                    await self._broadcast(
                        site,
                        {
                            "bridge": "device_offline",
                            "device_id": device_id,
                            "last_seen": record.last_seen,
                        },
                    )
                    LOGGER.info(
                        "Device %s disconnected from site %s",
                        device_id,
                        site.credentials.site_id,
                    )

    async def _send_snapshot(
        self, websocket: ServerConnection, record: DeviceRecord
    ) -> None:
        if not record.info and not record.components:
            return
        await websocket.send(
            json.dumps(
                {
                    "bridge": "device_snapshot",
                    "device_id": record.device_id,
                    "online": record.online,
                    "last_seen": record.last_seen,
                    "info": record.info,
                    "components": record.components,
                }
            )
        )

    async def _broadcast_snapshot(self, site: SiteState, record: DeviceRecord) -> None:
        await self._broadcast(
            site,
            {
                "bridge": "device_snapshot",
                "device_id": record.device_id,
                "online": record.online,
                "last_seen": record.last_seen,
                "info": record.info,
                "components": record.components,
            },
        )

    async def _broadcast(self, site: SiteState, message: dict[str, Any]) -> None:
        if not site.controllers:
            return
        payload = json.dumps(message)
        stale: list[ServerConnection] = []
        for controller in tuple(site.controllers):
            try:
                await controller.send(payload)
            except ConnectionClosed:
                stale.append(controller)
        for controller in stale:
            site.controllers.discard(controller)

    @staticmethod
    async def _send_error(
        websocket: ServerConnection,
        code: str,
        device_id: str | None = None,
        request_id: Any = None,
    ) -> None:
        message: dict[str, Any] = {"bridge": "error", "code": code}
        if device_id is not None:
            message["device_id"] = device_id
        if isinstance(request_id, int):
            message["request_id"] = request_id
        await websocket.send(json.dumps(message))


def _decode_json(raw: str | bytes) -> dict[str, Any] | None:
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _infer_device_id(frame: dict[str, Any]) -> str | None:
    src = frame.get("src")
    if not isinstance(src, str) or src == RELAY_SRC or not DEVICE_ID_RE.fullmatch(src):
        return None
    return src


def _is_dangerous_method(method: str) -> bool:
    return method in DANGEROUS_METHODS or method.startswith(DANGEROUS_PREFIXES)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def load_sites_from_env() -> list[SiteCredentials]:
    """Load either one simple site or a JSON map of multiple sites."""
    raw_sites = os.getenv("BRIDGE_SITES_JSON")
    if raw_sites:
        parsed = json.loads(raw_sites)
        if not isinstance(parsed, dict):
            raise ValueError("BRIDGE_SITES_JSON must be a JSON object")
        sites: list[SiteCredentials] = []
        for site_id, value in parsed.items():
            if not isinstance(site_id, str) or not isinstance(value, dict):
                raise ValueError("Each site must map to a credentials object")
            sites.append(
                SiteCredentials(
                    site_id=site_id,
                    device_token=_validated_token(value.get("device_token"), site_id),
                    ha_token=_validated_token(value.get("ha_token"), site_id),
                )
            )
        return sites

    site_id = os.getenv("BRIDGE_SITE_ID", "home")
    return [
        SiteCredentials(
            site_id=site_id,
            device_token=_validated_token(os.getenv("BRIDGE_DEVICE_TOKEN"), site_id),
            ha_token=_validated_token(os.getenv("BRIDGE_HA_TOKEN"), site_id),
        )
    ]


def _validated_token(value: Any, site_id: str) -> str:
    if not isinstance(value, str) or len(value) < 32:
        raise ValueError(f"Tokens for site {site_id!r} must contain at least 32 characters")
    return value


async def async_main() -> None:
    """Run until SIGINT or SIGTERM."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sites = load_sites_from_env()
    relay = BridgeRelay(sites)
    host = os.getenv("BRIDGE_HOST", "0.0.0.0")
    port = int(os.getenv("BRIDGE_PORT", "8765"))
    stop = asyncio.get_running_loop().create_future()
    for signame in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(
                signame, lambda: not stop.done() and stop.set_result(None)
            )
        except NotImplementedError:
            pass

    async with serve(
        relay.handle_connection,
        host,
        port,
        process_request=relay.process_request,
        ping_interval=20,
        ping_timeout=20,
        max_size=1_048_576,
        compression=None,
    ):
        LOGGER.info("Relay listening on %s:%s for %d site(s)", host, port, len(sites))
        await stop


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
