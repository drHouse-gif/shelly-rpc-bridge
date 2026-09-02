"""Shelly RPC Bridge integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .bridge import BridgeHub, BridgeReceiver, BridgeServer
from .const import CONF_DEVICE_TOKEN, DATA_SERVER, DOMAIN, PLATFORMS

type ShellyRpcBridgeConfigEntry = ConfigEntry[BridgeHub]


async def async_setup_entry(
    hass: HomeAssistant, entry: ShellyRpcBridgeConfigEntry
) -> bool:
    """Set up a direct Shelly RPC Bridge config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    server = domain_data.get(DATA_SERVER)
    if server is None:
        server = BridgeServer()
        domain_data[DATA_SERVER] = server
        hass.http.register_view(BridgeReceiver(server))

    token = entry.data[CONF_DEVICE_TOKEN]
    hub = BridgeHub(hass, token)
    server.register(token, hub)
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
    hub = entry.runtime_data
    await hub.async_stop()
    server: BridgeServer | None = hass.data.get(DOMAIN, {}).get(DATA_SERVER)
    if server is not None:
        server.unregister(entry.data[CONF_DEVICE_TOKEN], hub)
    return True
