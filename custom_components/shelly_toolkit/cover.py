"""Cover entities for Toolkit-owned Shelly devices."""

from __future__ import annotations

from homeassistant.components.cover import ATTR_POSITION, CoverEntity, CoverEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShellyToolkitConfigEntry
from .entity import ToolkitEntity, component_display_name, iter_components, owns_entities


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
                if component.kind != "cover":
                    continue
                unique = f"{device.id}:{component.key}"
                if unique in seen:
                    continue
                seen.add(unique)
                entities.append(ToolkitCover(runtime, device, component))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(runtime.coordinator.async_add_listener(discover))
    entry.async_on_unload(runtime.events.subscribe(lambda _event: discover()))


class ToolkitCover(ToolkitEntity, CoverEntity):
    """Control a Shelly Cover component."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, runtime, device, component) -> None:
        super().__init__(runtime, device, component, "cover")
        self._attr_name = component_display_name(component)

    @property
    def current_cover_position(self) -> int | None:
        value = self.component.status.get("current_pos")
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def is_opening(self) -> bool:
        return self.component.status.get("state") == "opening"

    @property
    def is_closing(self) -> bool:
        return self.component.status.get("state") == "closing"

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        return position == 0 if position is not None else None

    async def _command(self, method: str, params: dict | None = None) -> None:
        payload = {"id": self.component.component_id}
        if params:
            payload.update(params)
        await self.runtime.manager.async_call(self.device_id, f"Cover.{method}", payload)

    async def async_open_cover(self, **kwargs) -> None:
        await self._command("Open")

    async def async_close_cover(self, **kwargs) -> None:
        await self._command("Close")

    async def async_stop_cover(self, **kwargs) -> None:
        await self._command("Stop")

    async def async_set_cover_position(self, **kwargs) -> None:
        await self._command("GoToPosition", {"pos": kwargs[ATTR_POSITION]})
