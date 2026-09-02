"""Shelly RPC Bridge integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .bridge import BridgeHub
from .const import CONF_RELAY_URL, CONF_SITE_TOKEN, DOMAIN, PLATFORMS

type ShellyRpcBridgeConfigEntry = ConfigEntry[BridgeHub]


async def async_setup_entry(
    hass: HomeAssistant, entry: ShellyRpcBridgeConfigEntry
) -> bool:
    """Set up a Shelly RPC Bridge config entry."""
    hub = BridgeHub(
        hass,
        entry.data[CONF_RELAY_URL],
        entry.data[CONF_SITE_TOKEN],
    )
    entry.runtime_data = hub
    await hub.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ShellyRpcBridgeConfigEntry
) -> bool:
    """Unload a Shelly RPC Bridge config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_stop()
    return True
