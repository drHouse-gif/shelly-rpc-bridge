"""Generic boolean sensors for remote Shelly components."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShellyRpcBridgeConfigEntry
from .entity import BridgeEntity, component_display_name
from .models import RemoteComponent, RemoteDevice, flatten_scalars, value_at_path


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShellyRpcBridgeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    seen: set[str] = set()

    def discover(device: RemoteDevice) -> None:
        entities: list[BridgeBinarySensor] = []
        for component in device.components.values():
            for path, value in flatten_scalars(component.status):
                if not isinstance(value, bool):
                    continue
                if component.kind in {"switch", "cb", "light", "rgb", "rgbw"} and path[-1] in {
                    "output",
                    "on",
                }:
                    continue
                unique = f"{device.device_id}:{component.key}:{'.'.join(path)}"
                if unique in seen:
                    continue
                seen.add(unique)
                entities.append(BridgeBinarySensor(hub, device, component, path))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(hub.async_add_component_listener(discover))


class BridgeBinarySensor(BridgeEntity, BinarySensorEntity):
    """Expose one boolean status path."""

    def __init__(
        self,
        hub,
        device: RemoteDevice,
        component: RemoteComponent,
        path: tuple[str, ...],
    ) -> None:
        super().__init__(hub, device, component, "binary_" + "_".join(path))
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
