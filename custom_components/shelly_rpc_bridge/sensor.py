"""Generic measurement sensors for remote Shelly components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import (
    EntityCategory,
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ShellyRpcBridgeConfigEntry
from .entity import BridgeEntity, component_display_name
from .models import RemoteComponent, RemoteDevice, flatten_scalars, value_at_path

EXCLUDED_LEAVES = {
    "id",
    "ts",
    "output",
    "on",
    "brightness",
    "current_pos",
}


@dataclass(slots=True, frozen=True)
class MeasurementMetadata:
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    entity_category: EntityCategory | None = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShellyRpcBridgeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    seen: set[str] = set()

    def discover(device: RemoteDevice) -> None:
        entities: list[BridgeSensor] = []
        for component in device.components.values():
            for path, value in flatten_scalars(component.status):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                if path[-1].lower() in EXCLUDED_LEAVES:
                    continue
                unique = f"{device.device_id}:{component.key}:{'.'.join(path)}"
                if unique in seen:
                    continue
                seen.add(unique)
                entities.append(BridgeSensor(hub, device, component, path))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(hub.async_add_component_listener(discover))


class BridgeSensor(BridgeEntity, SensorEntity):
    """Expose one scalar status path as a Home Assistant sensor."""

    def __init__(
        self,
        hub,
        device: RemoteDevice,
        component: RemoteComponent,
        path: tuple[str, ...],
    ) -> None:
        suffix = "sensor_" + "_".join(path)
        super().__init__(hub, device, component, suffix)
        self.path = path
        readable = " ".join(part.replace("_", " ") for part in path).title()
        self._attr_name = f"{component_display_name(component)} {readable}"
        metadata = measurement_metadata(path)
        self._attr_native_unit_of_measurement = metadata.unit
        self._attr_device_class = metadata.device_class
        self._attr_state_class = metadata.state_class
        self._attr_entity_category = metadata.entity_category

    @property
    def native_value(self) -> Any:
        return value_at_path(self.component.status, self.path)


def measurement_metadata(path: tuple[str, ...]) -> MeasurementMetadata:
    """Map common Shelly status names to HA units and semantic classes."""
    leaf = path[-1].lower()
    joined = ".".join(path).lower()

    if leaf in {"tc", "temperature"} or "temperature" in leaf:
        return MeasurementMetadata(
            UnitOfTemperature.CELSIUS,
            SensorDeviceClass.TEMPERATURE,
            SensorStateClass.MEASUREMENT,
        )
    if leaf == "tf":
        return MeasurementMetadata(
            UnitOfTemperature.FAHRENHEIT,
            SensorDeviceClass.TEMPERATURE,
            SensorStateClass.MEASUREMENT,
        )
    if leaf in {"rh", "humidity"} or "humidity" in leaf:
        return MeasurementMetadata(
            PERCENTAGE,
            SensorDeviceClass.HUMIDITY,
            SensorStateClass.MEASUREMENT,
        )
    if "voltage" in leaf:
        return MeasurementMetadata(
            UnitOfElectricPotential.VOLT,
            SensorDeviceClass.VOLTAGE,
            SensorStateClass.MEASUREMENT,
        )
    if "current" in leaf:
        return MeasurementMetadata(
            UnitOfElectricCurrent.AMPERE,
            SensorDeviceClass.CURRENT,
            SensorStateClass.MEASUREMENT,
        )
    if "energy" in joined or (leaf == "total" and "energy" in joined):
        return MeasurementMetadata(
            UnitOfEnergy.WATT_HOUR,
            SensorDeviceClass.ENERGY,
            SensorStateClass.TOTAL_INCREASING,
        )
    if "aprt" in leaf or "apparent" in leaf:
        return MeasurementMetadata(
            UnitOfApparentPower.VOLT_AMPERE,
            SensorDeviceClass.APPARENT_POWER,
            SensorStateClass.MEASUREMENT,
        )
    if "power" in leaf:
        return MeasurementMetadata(
            UnitOfPower.WATT,
            SensorDeviceClass.POWER,
            SensorStateClass.MEASUREMENT,
        )
    if leaf in {"freq", "frequency"} or "frequency" in leaf:
        return MeasurementMetadata(
            UnitOfFrequency.HERTZ,
            SensorDeviceClass.FREQUENCY,
            SensorStateClass.MEASUREMENT,
        )
    if leaf in {"lux", "illuminance"}:
        return MeasurementMetadata(
            LIGHT_LUX,
            SensorDeviceClass.ILLUMINANCE,
            SensorStateClass.MEASUREMENT,
        )
    if "pressure" in leaf:
        return MeasurementMetadata(
            UnitOfPressure.HPA,
            SensorDeviceClass.ATMOSPHERIC_PRESSURE,
            SensorStateClass.MEASUREMENT,
        )
    if leaf in {"battery", "battery_pct", "percent", "soc"}:
        return MeasurementMetadata(
            PERCENTAGE,
            SensorDeviceClass.BATTERY,
            SensorStateClass.MEASUREMENT,
        )
    if leaf in {"rssi", "uptime", "ram_free", "fs_free"}:
        return MeasurementMetadata(entity_category=EntityCategory.DIAGNOSTIC)
    return MeasurementMetadata(state_class=SensorStateClass.MEASUREMENT)
