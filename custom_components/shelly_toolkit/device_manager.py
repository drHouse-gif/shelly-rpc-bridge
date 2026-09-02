"""Unified local, remote, and official Shelly target inventory."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import secrets
import socket
import time
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from .capabilities import async_discover_capabilities
from .const import (
    CONF_LOCAL_DEVICES,
    CONF_REMOTE_CREDENTIALS,
    CONF_TRANSPORT,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DOMAIN,
    HA_EVENT,
    MAX_DEVICES,
    TRANSPORT_HTTP,
)
from .events import EventStore
from .models import ConnectionKind, ToolkitDevice
from .remote import RemoteRpcTransport, RemoteServer, normalize_credentials
from .rpc import (
    EventCallback,
    HttpRpcTransport,
    RpcAuthError,
    RpcError,
    RpcProtocolError,
    RpcTransport,
    RpcUnavailableError,
    WebSocketRpcTransport,
)

LOGGER = logging.getLogger(__name__)


class OfficialShellyTransport:
    """Adapter around an already loaded official Shelly RPC coordinator."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator
        self.connected = bool(getattr(coordinator, "last_update_success", True))
        self.last_error: str | None = None

    async def async_connect(self) -> None:
        """Validate the official coordinator target."""
        await self.async_call("Shelly.GetDeviceInfo")

    async def async_call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Delegate to aioshelly through Home Assistant's coordinator."""
        try:
            result = await self._coordinator.device.call_rpc(method, params or {})
        except Exception as err:
            self.connected = False
            self.last_error = type(err).__name__
            if "auth" in type(err).__name__.lower():
                raise RpcAuthError("Official Shelly authentication failed") from err
            raise RpcUnavailableError(f"Official Shelly RPC failed: {err}") from err
        self.connected = True
        self.last_error = None
        return result

    async def async_close(self) -> None:
        """Do not close a transport owned by the official integration."""
        self.connected = False

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """The official integration owns its push listener."""


class DeviceManager:
    """Manage all RPC targets behind one consistent API."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        remote_server: RemoteServer,
        events: EventStore,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.remote_server = remote_server
        self.events = events
        self.devices: dict[str, ToolkitDevice] = {}
        self.transports: dict[str, RpcTransport] = {}
        self._local_ids: set[str] = set()
        self._remote_ids: set[str] = set()
        self._component_listeners: set[Callable[[ToolkitDevice], None]] = set()

    async def async_start(self) -> None:
        """Create transports and make the manager available immediately."""
        credentials = normalize_credentials(self.entry.data.get(CONF_REMOTE_CREDENTIALS, []))
        if credentials != self.entry.data.get(CONF_REMOTE_CREDENTIALS, []):
            self._update_entry_data(CONF_REMOTE_CREDENTIALS, credentials)
        self.remote_server.configure(
            credentials,
            bind_callback=self.async_bind_credential,
            connect_callback=self.async_remote_connected,
            disconnect_callback=self.async_remote_disconnected,
        )
        for config in self.entry.data.get(CONF_LOCAL_DEVICES, []):
            if isinstance(config, dict):
                self._create_local(config)
        await self.async_sync_official_devices()
        if self._local_ids:
            await asyncio.gather(
                *(self.async_refresh_device(device_id) for device_id in self._local_ids)
            )

    async def async_close(self) -> None:
        """Close only Toolkit-owned transports."""
        for device_id, transport in tuple(self.transports.items()):
            if not device_id.startswith("official:"):
                await transport.async_close()
        self.transports.clear()
        self.devices.clear()

    def _create_local(self, config: dict[str, Any]) -> str:
        device_id = str(config.get("id") or f"local:{secrets.token_hex(6)}")
        if not device_id.startswith("local:"):
            device_id = f"local:{device_id}"
        transport = self._transport_from_local(config)
        transport.set_event_callback(self._event_callback(device_id))
        self.transports[device_id] = transport
        self.devices[device_id] = ToolkitDevice(
            id=device_id,
            connection=ConnectionKind.LOCAL,
            name=str(config.get("name") or config.get(CONF_HOST) or device_id),
            host=str(config[CONF_HOST]),
            port=int(config.get(CONF_PORT, DEFAULT_PORT)),
        )
        self._local_ids.add(device_id)
        return device_id

    def _transport_from_local(self, config: dict[str, Any]) -> RpcTransport:
        cls = (
            HttpRpcTransport
            if config.get(CONF_TRANSPORT) == TRANSPORT_HTTP
            else WebSocketRpcTransport
        )
        return cls(
            async_get_clientsession(self.hass),
            str(config[CONF_HOST]),
            port=int(config.get(CONF_PORT, DEFAULT_PORT)),
            username=str(config.get(CONF_USERNAME, "admin")),
            password=config.get(CONF_PASSWORD),
            use_ssl=bool(config.get("use_ssl", False)),
            verify_ssl=bool(config.get(CONF_VERIFY_SSL, False)),
        )

    async def async_sync_official_devices(self) -> None:
        """Expose loaded official Shelly RPC entries as non-duplicating targets."""
        current: set[str] = set()
        registry = dr.async_get(self.hass)
        for official_entry in self.hass.config_entries.async_entries("shelly"):
            if official_entry.state is not ConfigEntryState.LOADED:
                continue
            runtime = getattr(official_entry, "runtime_data", None)
            coordinator = getattr(runtime, "rpc", None)
            if coordinator is None:
                continue
            unique = official_entry.unique_id or official_entry.entry_id
            device_id = f"official:{unique}"
            current.add(device_id)
            transport = self.transports.get(device_id)
            if not isinstance(transport, OfficialShellyTransport):
                transport = OfficialShellyTransport(coordinator)
                self.transports[device_id] = transport
            device = self.devices.setdefault(
                device_id,
                ToolkitDevice(
                    id=device_id,
                    connection=ConnectionKind.OFFICIAL,
                    name=official_entry.title,
                    host=official_entry.data.get(CONF_HOST),
                    port=official_entry.data.get(CONF_PORT),
                ),
            )
            matches = dr.async_entries_for_config_entry(registry, official_entry.entry_id)
            if matches:
                device.registry_device_id = matches[0].id
        for device_id in tuple(self.devices):
            if device_id.startswith("official:") and device_id not in current:
                self.devices.pop(device_id, None)
                self.transports.pop(device_id, None)

    async def async_refresh_all(self) -> list[dict[str, Any]]:
        """Refresh polling targets and synchronize official entries."""
        await self.async_sync_official_devices()
        polling = [
            device_id
            for device_id, device in self.devices.items()
            if device.connection in {ConnectionKind.LOCAL, ConnectionKind.OFFICIAL}
        ]
        await asyncio.gather(*(self.async_refresh_device(item) for item in polling))
        return self.list_devices()

    async def async_refresh_device(self, device_id: str) -> ToolkitDevice:
        """Refresh real device info, status, config, and capabilities."""
        device = self.get_device(device_id)
        transport = self.get_transport(device_id)
        try:
            info, status, config = await asyncio.gather(
                transport.async_call("Shelly.GetDeviceInfo"),
                transport.async_call("Shelly.GetStatus"),
                transport.async_call("Shelly.GetConfig"),
            )
            if not all(isinstance(item, dict) for item in (info, status, config)):
                raise RpcProtocolError("Shelly identity, status, and config must be objects")
            device.info = info
            device.status = status
            device.config = config
            if not device.capabilities.components:
                device.capabilities = await async_discover_capabilities(transport)
            device.record_rpc_success()
            device.mark_seen()
            self._sync_registry(device)
            self._notify_components(device)
        except RpcError as err:
            device.record_rpc_failure()
            device.online = False
            device.last_error = type(err).__name__
            LOGGER.debug("Could not refresh %s: %s", device_id, err)
        return device

    def async_add_component_listener(
        self, callback: Callable[[ToolkitDevice], None]
    ) -> Callable[[], None]:
        """Subscribe to component discovery and replay current devices."""
        self._component_listeners.add(callback)
        for device in self.devices.values():
            if device.status or device.capabilities.components:
                callback(device)
        return lambda: self._component_listeners.discard(callback)

    def _notify_components(self, device: ToolkitDevice) -> None:
        """Notify entity platforms after a component snapshot or push update."""
        for callback in tuple(self._component_listeners):
            callback(device)

    def _event_callback(self, device_id: str) -> EventCallback:
        """Build a typed push callback bound to one Toolkit target."""

        async def handle(frame: dict[str, Any]) -> None:
            await self.async_handle_frame(device_id, frame)

        return handle

    async def async_call(
        self,
        device_id: str,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute one RPC call and update connection state."""
        device = self.get_device(device_id)
        transport = self.get_transport(device_id)
        try:
            result = await transport.async_call(method, params)
        except RpcError as err:
            device.record_rpc_failure()
            device.last_error = type(err).__name__
            if isinstance(err, RpcUnavailableError):
                device.online = False
            raise
        device.record_rpc_success()
        device.mark_seen()
        return result

    async def async_handle_frame(self, device_id: str, frame: dict[str, Any]) -> None:
        """Apply push state/config and forward bounded events."""
        device = self.devices.get(device_id)
        if device is None:
            return
        device.mark_seen()
        method = frame.get("method")
        params = frame.get("params")
        if isinstance(params, dict):
            if method == "NotifyFullStatus":
                device.status = {
                    key: deepcopy(value)
                    for key, value in params.items()
                    if isinstance(value, dict) and key not in {"ts", "rev"}
                }
            elif method == "NotifyStatus":
                for key, value in params.items():
                    if isinstance(value, dict) and key not in {"ts", "rev"}:
                        current = device.status.setdefault(key, {})
                        if isinstance(current, dict):
                            current.update(value)
            elif method == "NotifyFullConfig":
                device.config = {
                    key: deepcopy(value)
                    for key, value in params.items()
                    if isinstance(value, dict) and key not in {"ts", "rev"}
                }
            elif method == "NotifyConfig":
                for key, value in params.items():
                    if isinstance(value, dict) and key not in {"ts", "rev"}:
                        current = device.config.setdefault(key, {})
                        if isinstance(current, dict):
                            current.update(value)
        if method in {"NotifyStatus", "NotifyFullStatus", "NotifyConfig", "NotifyFullConfig"}:
            self._notify_components(device)
        for event in self.events.add_frame(device_id, frame):
            self.hass.bus.async_fire(HA_EVENT, event.as_dict())

    async def async_remote_connected(
        self,
        raw_device_id: str,
        info: dict[str, Any],
        transport: RemoteRpcTransport,
    ) -> None:
        """Register a newly authenticated remote target."""
        device_id = f"remote:{raw_device_id}"
        transport.device_id = device_id
        transport.set_event_callback(self._event_callback(device_id))
        self.transports[device_id] = transport
        device = self.devices.setdefault(
            device_id,
            ToolkitDevice(
                id=device_id,
                connection=ConnectionKind.REMOTE,
                name=str(info.get("name") or raw_device_id),
            ),
        )
        device.info.update(info)
        device.mark_seen()
        self._remote_ids.add(device_id)
        self._sync_registry(device)
        self.entry.async_create_background_task(
            self.hass,
            self.async_refresh_device(device_id),
            f"Refresh remote Shelly {raw_device_id}",
            eager_start=True,
        )

    async def async_remote_disconnected(self, raw_device_id: str) -> None:
        """Mark a remote target offline but retain last-known metadata."""
        device_id = f"remote:{raw_device_id}"
        self.transports.pop(device_id, None)
        if (device := self.devices.get(device_id)) is not None:
            device.online = False
            device.last_seen = time.time()

    async def async_bind_credential(self, credential_id: str, raw_device_id: str) -> None:
        """Persist first-use device binding without storing the secret."""
        credentials = normalize_credentials(self.entry.data.get(CONF_REMOTE_CREDENTIALS, []))
        for item in credentials:
            if item["id"] == credential_id:
                item["bound_device_id"] = raw_device_id
                break
        self._update_entry_data(CONF_REMOTE_CREDENTIALS, credentials)

    async def async_add_local(self, config: dict[str, Any]) -> ToolkitDevice:
        """Validate a target is Shelly Gen2+ before persisting it."""
        candidate = dict(config)
        candidate["id"] = f"local:{secrets.token_hex(8)}"
        local = [
            dict(item)
            for item in self.entry.data.get(CONF_LOCAL_DEVICES, [])
            if isinstance(item, dict)
        ]
        candidate_host = str(candidate[CONF_HOST]).rstrip(".").lower()
        candidate_port = int(candidate.get(CONF_PORT, DEFAULT_PORT))
        if any(
            str(item.get(CONF_HOST, "")).rstrip(".").lower() == candidate_host
            and int(item.get(CONF_PORT, DEFAULT_PORT)) == candidate_port
            for item in local
        ):
            raise ValueError("A local target with this host and port already exists")
        if len(self._local_ids | self._remote_ids) >= MAX_DEVICES:
            raise ValueError("Shelly Toolkit device limit reached")
        await _async_validate_local_target(str(candidate[CONF_HOST]), candidate_port)
        transport = self._transport_from_local(candidate)
        try:
            info = await transport.async_call("Shelly.GetDeviceInfo")
            if not isinstance(info, dict):
                raise RpcUnavailableError("Target returned invalid device information")
            if not isinstance(info.get("gen"), int) or int(info["gen"]) < 2:
                raise RpcUnavailableError("Target is not a Shelly Gen2+ device")
        finally:
            await transport.async_close()
        advertised_mac = info.get("mac")
        normalized_mac = (
            "".join(char for char in advertised_mac if char.isalnum()).upper()
            if isinstance(advertised_mac, str)
            else None
        )
        if normalized_mac:
            duplicate = next(
                (item for item in self.devices.values() if item.mac == normalized_mac), None
            )
            if duplicate is not None:
                if duplicate.connection is ConnectionKind.OFFICIAL:
                    return duplicate
                raise ValueError("This Shelly device is already registered")
        candidate["name"] = str(candidate.get("name") or info.get("name") or info.get("id"))
        local.append(candidate)
        self._update_entry_data(CONF_LOCAL_DEVICES, local)
        device_id = self._create_local(candidate)
        device = await self.async_refresh_device(device_id)
        return device

    async def async_remove_local(self, device_id: str) -> None:
        """Remove one Toolkit-owned local target."""
        if device_id not in self._local_ids:
            raise KeyError(device_id)
        if (transport := self.transports.pop(device_id, None)) is not None:
            await transport.async_close()
        if (device := self.devices.get(device_id)) is not None:
            device.online = False
            self._notify_components(device)
        self.devices.pop(device_id, None)
        self._local_ids.discard(device_id)
        local = [
            item
            for item in self.entry.data.get(CONF_LOCAL_DEVICES, [])
            if isinstance(item, dict) and item.get("id") != device_id
        ]
        self._update_entry_data(CONF_LOCAL_DEVICES, local)

    def get_device(self, device_id: str) -> ToolkitDevice:
        """Get one target."""
        try:
            return self.devices[device_id]
        except KeyError as err:
            raise KeyError(f"Unknown Shelly Toolkit device: {device_id}") from err

    def get_transport(self, device_id: str) -> RpcTransport:
        """Get one live transport."""
        try:
            return self.transports[device_id]
        except KeyError as err:
            raise RpcUnavailableError(f"Device is offline: {device_id}") from err

    def list_devices(self) -> list[dict[str, Any]]:
        """Return stable, panel-safe inventory."""
        # Capability snapshots may contain component config. Apply the same
        # recursive scrub used by backups before crossing the panel/diagnostic API.
        from .backup import scrub_secrets

        devices, _ = scrub_secrets([self.devices[key].as_dict() for key in sorted(self.devices)])
        return devices

    def _sync_registry(self, device: ToolkitDevice) -> None:
        if device.connection is ConnectionKind.OFFICIAL:
            return
        registry = dr.async_get(self.hass)
        connections: set[tuple[str, str]] = set()
        if device.mac:
            connections.add((CONNECTION_NETWORK_MAC, dr.format_mac(device.mac)))
        entry = registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, device.id)},
            connections=connections,
            manufacturer="Shelly Group",
            model=device.model,
            name=device.name,
            sw_version=device.firmware,
            configuration_url=f"http://{device.host}" if device.host else None,
        )
        device.registry_device_id = entry.id

    def _update_entry_data(self, key: str, value: Any) -> None:
        data = deepcopy(dict(self.entry.data))
        data[key] = value
        self.hass.config_entries.async_update_entry(self.entry, data=data)


async def _async_validate_local_target(host: str, port: int) -> None:
    """Resolve a user-added target and reject SSRF-sensitive address classes."""
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except OSError as err:
        raise RpcUnavailableError(f"Could not resolve local target: {host}") from err
    parsed = {ipaddress.ip_address(item[4][0]) for item in addresses}
    if not parsed or any(not _is_safe_local_address(address) for address in parsed):
        raise RpcUnavailableError(
            "Local targets must resolve only to private, non-loopback addresses"
        )


def _is_safe_local_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is suitable for an explicitly added LAN device."""
    return (
        address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )
