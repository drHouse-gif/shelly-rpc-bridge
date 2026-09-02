"""Light entities for Toolkit-owned Shelly devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShellyToolkitConfigEntry
from .entity import ToolkitEntity, component_display_name, iter_components, owns_entities

SUPPORTED_KINDS = {"light", "rgb", "rgbw"}
NAMESPACES = {"light": "Light", "rgb": "RGB", "rgbw": "RGBW"}


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
                entities.append(ToolkitLight(runtime, device, component))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(runtime.manager.async_add_component_listener(lambda _device: discover()))
    entry.async_on_unload(runtime.coordinator.async_add_listener(discover))
    entry.async_on_unload(runtime.events.subscribe(lambda _event: discover()))


class ToolkitLight(ToolkitEntity, LightEntity):
    """Control a Shelly Light/RGB/RGBW component."""

    def __init__(self, runtime, device, component) -> None:
        super().__init__(runtime, device, component, "light")
        self._attr_name = component_display_name(component)
        if component.kind == "rgb":
            self._attr_supported_color_modes = {ColorMode.RGB}
        elif component.kind == "rgbw":
            self._attr_supported_color_modes = {ColorMode.RGBW}
        elif "brightness" in component.status:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool | None:
        output = self.component.status.get("output")
        return output if isinstance(output, bool) else None

    @property
    def color_mode(self) -> ColorMode:
        return next(iter(self._attr_supported_color_modes))

    @property
    def brightness(self) -> int | None:
        value = self.component.status.get("brightness")
        if not isinstance(value, (int, float)):
            return None
        return round(max(0, min(100, value)) * 255 / 100)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        value = self.component.status.get("rgb")
        if isinstance(value, list) and len(value) >= 3:
            return (int(value[0]), int(value[1]), int(value[2]))
        return None

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        rgb = self.component.status.get("rgb")
        white = self.component.status.get("white")
        if isinstance(rgb, list) and len(rgb) >= 3 and isinstance(white, int):
            return (int(rgb[0]), int(rgb[1]), int(rgb[2]), white)
        return None

    async def async_turn_on(self, **kwargs) -> None:
        params: dict[str, Any] = {"id": self.component.component_id, "on": True}
        optimistic: dict[str, Any] = {"output": True}
        if ATTR_BRIGHTNESS in kwargs:
            percent = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            params["brightness"] = percent
            optimistic["brightness"] = percent
        if ATTR_RGB_COLOR in kwargs:
            params["rgb"] = list(kwargs[ATTR_RGB_COLOR])
            optimistic["rgb"] = list(kwargs[ATTR_RGB_COLOR])
        if ATTR_RGBW_COLOR in kwargs:
            red, green, blue, white = kwargs[ATTR_RGBW_COLOR]
            params["rgb"] = [red, green, blue]
            params["white"] = white
            optimistic.update({"rgb": [red, green, blue], "white": white})
        await self.runtime.manager.async_call(
            self.device_id, f"{NAMESPACES[self.component.kind]}.Set", params
        )
        self.device.status.setdefault(self.component_key, {}).update(optimistic)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.runtime.manager.async_call(
            self.device_id,
            f"{NAMESPACES[self.component.kind]}.Set",
            {"id": self.component.component_id, "on": False},
        )
        self.device.status.setdefault(self.component_key, {})["output"] = False
        self.async_write_ha_state()
