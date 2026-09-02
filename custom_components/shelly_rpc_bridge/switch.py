"""Switch and circuit-breaker entities."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShellyRpcBridgeConfigEntry
from .entity import BridgeEntity, component_display_name
from .models import RemoteComponent, RemoteDevice

SUPPORTED_KINDS = {"switch", "cb"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShellyRpcBridgeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    seen: set[str] = set()

    def discover(device: RemoteDevice) -> None:
        entities: list[BridgeSwitch] = []
        for component in device.components.values():
            if component.kind not in SUPPORTED_KINDS:
                continue
            unique = f"{device.device_id}:{component.key}"
            if unique in seen:
                continue
            seen.add(unique)
            entities.append(BridgeSwitch(hub, device, component))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(hub.async_add_component_listener(discover))


class BridgeSwitch(BridgeEntity, SwitchEntity):
    """Control a remote Switch or CB component."""

    def __init__(self, hub, device: RemoteDevice, component: RemoteComponent) -> None:
        super().__init__(hub, device, component, "output")
        self._attr_name = component_display_name(component)

    @property
    def is_on(self) -> bool | None:
        output = self.component.status.get("output")
        return output if isinstance(output, bool) else None

    async def async_turn_on(self, **kwargs) -> None:
        namespace = "CB" if self.component.kind == "cb" else "Switch"
        await self.hub.async_rpc(
            self.device_id,
            f"{namespace}.Set",
            {"id": self.component.component_id, "on": True}
            if namespace == "Switch"
            else {"id": self.component.component_id, "output": True},
        )
        self.hub.set_component_status(
            self.device_id, self.component_key, {"output": True}
        )

    async def async_turn_off(self, **kwargs) -> None:
        namespace = "CB" if self.component.kind == "cb" else "Switch"
        await self.hub.async_rpc(
            self.device_id,
            f"{namespace}.Set",
            {"id": self.component.component_id, "on": False}
            if namespace == "Switch"
            else {"id": self.component.component_id, "output": False},
        )
        self.hub.set_component_status(
            self.device_id, self.component_key, {"output": False}
        )
