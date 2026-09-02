"""Shared dynamic entities for Shelly Toolkit targets."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import ToolkitRuntime
from .const import DOMAIN
from .models import ConnectionKind, ToolkitDevice


@dataclass(slots=True)
class ToolkitComponent:
    """Last-known state/config for one RPC component."""

    key: str
    config: dict[str, Any]
    status: dict[str, Any]

    @property
    def kind(self) -> str:
        return self.key.split(":", 1)[0].lower()

    @property
    def component_id(self) -> int:
        try:
            return int(self.key.split(":", 1)[1])
        except IndexError, ValueError:
            return 0


def iter_components(device: ToolkitDevice) -> Iterator[ToolkitComponent]:
    """Yield all component-like status/config objects known for a target."""
    keys = set(device.status) | set(device.config) | set(device.capabilities.components)
    for key in sorted(keys):
        status = device.status.get(key)
        config = device.config.get(key)
        discovered = device.capabilities.components.get(key, {})
        if not isinstance(status, dict):
            raw = discovered.get("status") if isinstance(discovered, dict) else None
            status = raw if isinstance(raw, dict) else {}
        if not isinstance(config, dict):
            raw = discovered.get("config") if isinstance(discovered, dict) else None
            config = raw if isinstance(raw, dict) else {}
        if status or config:
            yield ToolkitComponent(key, config, status)


def component_for(device: ToolkitDevice, key: str) -> ToolkitComponent:
    """Return a live component view."""
    for component in iter_components(device):
        if component.key == key:
            return component
    return ToolkitComponent(key, {}, {})


def flatten_scalars(
    value: dict[str, Any], prefix: tuple[str, ...] = (), max_depth: int = 3
) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Yield scalar paths from a nested status object."""
    if len(prefix) >= max_depth:
        return
    for key, child in value.items():
        path = (*prefix, str(key))
        if isinstance(child, dict):
            yield from flatten_scalars(child, path, max_depth)
        elif isinstance(child, (str, int, float, bool)) or child is None:
            yield path, child


def value_at_path(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Read a flattened scalar path."""
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


class ToolkitEntity(Entity):
    """Base entity bound to one Toolkit-owned Shelly component."""

    _attr_has_entity_name = True

    def __init__(
        self,
        runtime: ToolkitRuntime,
        device: ToolkitDevice,
        component: ToolkitComponent,
        suffix: str,
    ) -> None:
        self.runtime = runtime
        self.device_id = device.id
        self._last_device = device
        self.component_key = component.key
        safe_device = device.id.replace(":", "_")
        safe_component = component.key.replace(":", "_")
        self._attr_unique_id = f"{safe_device}_{safe_component}_{suffix}"
        self._remove_event_listener: Callable[[], None] | None = None
        self._remove_coordinator_listener: Callable[[], None] | None = None

    @property
    def device(self) -> ToolkitDevice:
        return self.runtime.manager.devices.get(self.device_id, self._last_device)

    @property
    def component(self) -> ToolkitComponent:
        return component_for(self.device, self.component_key)

    @property
    def available(self) -> bool:
        return self.device.online

    @property
    def device_info(self) -> DeviceInfo:
        device = self.device
        return DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            manufacturer="Shelly Group",
            model=device.model,
            sw_version=device.firmware,
            serial_number=device.mac,
            configuration_url=f"http://{device.host}" if device.host else None,
        )

    async def async_added_to_hass(self) -> None:
        def handle_event(event) -> None:
            if event.device_id == self.device_id:
                self.async_write_ha_state()

        self._remove_event_listener = self.runtime.events.subscribe(handle_event)
        self._remove_coordinator_listener = self.runtime.coordinator.async_add_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_event_listener is not None:
            self._remove_event_listener()
            self._remove_event_listener = None
        if self._remove_coordinator_listener is not None:
            self._remove_coordinator_listener()
            self._remove_coordinator_listener = None


def component_display_name(component: ToolkitComponent) -> str:
    """Use configured component name, otherwise its RPC key."""
    name = component.config.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return component.key.replace(":", " ").upper()


def owns_entities(device: ToolkitDevice) -> bool:
    """Toolkit owns entities for its local and Remote Pair transports."""
    return device.connection in {ConnectionKind.LOCAL, ConnectionKind.REMOTE}
