"""Generic boolean sensors for Toolkit-owned Shelly devices."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShellyToolkitConfigEntry
from .entity import (
    ToolkitEntity,
    component_display_name,
    flatten_scalars,
    iter_components,
    owns_entities,
    value_at_path,
)


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
                for path, value in flatten_scalars(component.status):
                    if not isinstance(value, bool):
                        continue
                    if component.kind in {"switch", "cb", "light", "rgb", "rgbw"} and path[-1] in {"output", "on"}:
                        continue
                    unique = f"{device.id}:{component.key}:{'.'.join(path)}"
                    if unique in seen:
                        continue
                    seen.add(unique)
                    entities.append(ToolkitBinarySensor(runtime, device, component, path))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(runtime.coordinator.async_add_listener(discover))
    entry.async_on_unload(runtime.events.subscribe(lambda _event: discover()))


class ToolkitBinarySensor(ToolkitEntity, BinarySensorEntity):
    """Expose one boolean Shelly status path."""

    def __init__(self, runtime, device, component, path: tuple[str, ...]) -> None:
        super().__init__(runtime, device, component, "binary_" + "_".join(path))
        self.path = path
        readable = " ".join(part.replace("_", " ") for part in path).title()
        self._attr_name = f"{component_display_name(component)} {readable}"
        leaf = path[-1].lower()
        if any(word in leaf for word in ("fault", "error", "overtemp", "alarm")):
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        elif leaf in {"connected", "online"}:
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        elif component.kind == "input":
            self._attr_device_class = BinarySensorDeviceClass.POWER

    @property
    def is_on(self) -> bool | None:
        value = value_at_path(self.component.status, self.path)
        return value if isinstance(value, bool) else None
