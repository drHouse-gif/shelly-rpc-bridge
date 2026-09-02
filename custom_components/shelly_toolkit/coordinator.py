"""Periodic refresh coordinator for Shelly Toolkit."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .device_manager import DeviceManager

LOGGER = logging.getLogger(__name__)


class ToolkitCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Refresh local and official targets while remote targets stay push-driven."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, manager: DeviceManager
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.manager = manager

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Refresh targets without failing the config entry for one offline device."""
        return await self.manager.async_refresh_all()

