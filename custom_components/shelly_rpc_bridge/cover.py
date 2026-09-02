"""Cover entities."""

from __future__ import annotations

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShellyRpcBridgeConfigEntry
from .entity import BridgeEntity, component_display_name
from .models import RemoteComponent, RemoteDevice


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShellyRpcBridgeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    seen: set[str] = set()

    def discover(device: RemoteDevice) -> None:
        entities: list[BridgeCover] = []
        for component in device.components.values():
            if component.kind != "cover":
                continue
            unique = f"{device.device_id}:{component.key}"
            if unique in seen:
                continue
            seen.add(unique)
            entities.append(BridgeCover(hub, device, component))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(hub.async_add_component_listener(discover))


class BridgeCover(BridgeEntity, CoverEntity):
    """Control a remote Shelly Cover component."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, hub, device: RemoteDevice, component: RemoteComponent) -> None:
        super().__init__(hub, device, component, "cover")
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
        await self.hub.async_rpc(self.device_id, f"Cover.{method}", payload)

    async def async_open_cover(self, **kwargs) -> None:
        await self._command("Open")

    async def async_close_cover(self, **kwargs) -> None:
        await self._command("Close")

    async def async_stop_cover(self, **kwargs) -> None:
        await self._command("Stop")

    async def async_set_cover_position(self, **kwargs) -> None:
        await self._command("GoToPosition", {"pos": kwargs[ATTR_POSITION]})
