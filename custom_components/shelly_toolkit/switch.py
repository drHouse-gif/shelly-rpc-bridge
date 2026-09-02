"""Switch and circuit-breaker entities."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShellyToolkitConfigEntry
from .entity import ToolkitEntity, component_display_name, iter_components, owns_entities

SUPPORTED_KINDS = {"switch", "cb"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShellyToolkitConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    seen: set[str] = set()

    def discover() -> None:
        entities = []
        for device in runtime.manager.devices.values():
            if not owns_entities(device):
                continue
            for component in iter_components(device):
                if component.kind not in SUPPORTED_KINDS:
                    continue
                unique = f"{device.id}:{component.key}"
                if unique in seen:
                    continue
                seen.add(unique)
                entities.append(ToolkitSwitch(runtime, device, component))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(runtime.manager.async_add_component_listener(lambda _device: discover()))
    entry.async_on_unload(runtime.coordinator.async_add_listener(discover))
    entry.async_on_unload(runtime.events.subscribe(lambda _event: discover()))


class ToolkitSwitch(ToolkitEntity, SwitchEntity):
    """Control a Shelly Switch or CB component."""

    def __init__(self, runtime, device, component) -> None:
        super().__init__(runtime, device, component, "output")
        self._attr_name = component_display_name(component)

    @property
    def is_on(self) -> bool | None:
        output = self.component.status.get("output")
        return output if isinstance(output, bool) else None

    async def _set_output(self, value: bool) -> None:
        namespace = "CB" if self.component.kind == "cb" else "Switch"
        params = {"id": self.component.component_id}
        params["output" if namespace == "CB" else "on"] = value
        await self.runtime.manager.async_call(self.device_id, f"{namespace}.Set", params)
        self.device.status.setdefault(self.component_key, {})["output"] = value
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set_output(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set_output(False)
