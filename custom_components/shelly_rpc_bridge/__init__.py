"""Shelly RPC Bridge integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .bridge import BridgeHub, BridgeReceiver, BridgeServer
from .const import (
    CONF_DEVICE_TOKEN,
    CONF_DEVICE_TOKENS,
    CONF_DEVICE_URL,
    DATA_SERVER,
    DOMAIN,
    PLATFORMS,
)

type ShellyRpcBridgeConfigEntry = ConfigEntry[BridgeHub]


def tokens_from_entry(entry: ConfigEntry) -> list[dict[str, str]]:
    """Return current token records, including legacy 0.2.x entries."""
    raw = entry.data.get(CONF_DEVICE_TOKENS)
    if isinstance(raw, list):
        result: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            token = item.get("token")
            token_id = item.get("id")
            name = item.get("name")
            if isinstance(token, str) and isinstance(token_id, str) and isinstance(name, str):
                result.append({"id": token_id, "name": name, "token": token})
        if result:
            return result

    legacy = entry.data.get(CONF_DEVICE_TOKEN)
    if isinstance(legacy, str) and legacy:
        return [{"id": "primary", "name": "Primary", "token": legacy}]
    return []


def normalized_entry_data(entry: ConfigEntry, tokens: list[dict[str, str]]) -> dict[str, Any]:
    """Build v0.3 entry data and discard legacy single-token fields."""
    data = dict(entry.data)
    data.pop(CONF_DEVICE_TOKEN, None)
    data.pop(CONF_DEVICE_URL, None)
    data[CONF_DEVICE_TOKENS] = tokens
    return data


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

    tokens = tokens_from_entry(entry)
    if entry.data.get(CONF_DEVICE_TOKENS) != tokens:
        hass.config_entries.async_update_entry(
            entry,
            data=normalized_entry_data(entry, tokens),
            version=3,
            minor_version=0,
        )

    hub = BridgeHub(hass)
    entry.runtime_data = hub
    await hub.async_start()
    await server.async_set_tokens(hub, (item["token"] for item in tokens))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ShellyRpcBridgeConfigEntry
) -> bool:
    """Unload a Shelly RPC Bridge config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hub = entry.runtime_data
    server: BridgeServer | None = hass.data.get(DOMAIN, {}).get(DATA_SERVER)
    if server is not None:
        await server.async_unregister_hub(hub)
    await hub.async_stop()
    return True
