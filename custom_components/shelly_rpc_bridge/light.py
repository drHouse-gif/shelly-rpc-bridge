"""Light entities."""

from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShellyRpcBridgeConfigEntry
from .entity import BridgeEntity, component_display_name
from .models import RemoteComponent, RemoteDevice

SUPPORTED_KINDS = {"light", "rgb", "rgbw"}
NAMESPACES = {"light": "Light", "rgb": "RGB", "rgbw": "RGBW"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShellyRpcBridgeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    seen: set[str] = set()

    def discover(device: RemoteDevice) -> None:
        entities: list[BridgeLight] = []
        for component in device.components.values():
            if component.kind not in SUPPORTED_KINDS:
                continue
            unique = f"{device.device_id}:{component.key}"
            if unique in seen:
                continue
            seen.add(unique)
            entities.append(BridgeLight(hub, device, component))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(hub.async_add_component_listener(discover))


class BridgeLight(BridgeEntity, LightEntity):
    """Control a remote Shelly light component."""

    def __init__(self, hub, device: RemoteDevice, component: RemoteComponent) -> None:
        super().__init__(hub, device, component, "light")
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
            return tuple(int(x) for x in value[:3])
        return None

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        rgb = self.component.status.get("rgb")
        white = self.component.status.get("white")
        if isinstance(rgb, list) and len(rgb) >= 3 and isinstance(white, int):
            return (*tuple(int(x) for x in rgb[:3]), white)
        return None

    async def async_turn_on(self, **kwargs) -> None:
        params = {"id": self.component.component_id, "on": True}
        optimistic = {"output": True}
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
        await self.hub.async_rpc(
            self.device_id, f"{NAMESPACES[self.component.kind]}.Set", params
        )
        self.hub.set_component_status(
            self.device_id, self.component_key, optimistic
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.hub.async_rpc(
            self.device_id,
            f"{NAMESPACES[self.component.kind]}.Set",
            {"id": self.component.component_id, "on": False},
        )
        self.hub.set_component_status(
            self.device_id, self.component_key, {"output": False}
        )
