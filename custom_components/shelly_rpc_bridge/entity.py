"""Shared entities for Shelly RPC Bridge."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .bridge import BridgeHub
from .const import DOMAIN
from .models import RemoteComponent, RemoteDevice


class BridgeEntity(Entity):
    """Base class bound to one remote Shelly component."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hub: BridgeHub,
        device: RemoteDevice,
        component: RemoteComponent,
        suffix: str,
    ) -> None:
        self.hub = hub
        self.device_id = device.device_id
        self.component_key = component.key
        self._attr_unique_id = (
            f"{device.device_id}_{component.key}_{suffix}".replace(":", "_")
        )
        self._remove_listener: Callable[[], None] | None = None

    @property
    def device(self) -> RemoteDevice:
        return self.hub.devices[self.device_id]

    @property
    def component(self) -> RemoteComponent:
        return self.device.components[self.component_key]

    @property
    def available(self) -> bool:
        return self.hub.connected and self.device.available

    @property
    def device_info(self) -> DeviceInfo:
        info = self.device.info
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=info.get("name") or info.get("id") or self.device_id,
            manufacturer="Shelly",
            model=info.get("model") or info.get("app"),
            sw_version=info.get("ver") or info.get("fw_id"),
            serial_number=info.get("mac"),
        )

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self.hub.async_add_update_listener(
            self.device_id, self._handle_update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    def _handle_update(self) -> None:
        self.async_write_ha_state()


def component_display_name(component: RemoteComponent) -> str:
    """Use the configured Shelly name, falling back to its RPC key."""
    name = component.config.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return component.key.replace(":", " ").upper()
