"""Home Assistant downloadable diagnostics with mandatory redaction."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ShellyToolkitConfigEntry
from .const import CONF_LOCAL_DEVICES, CONF_REMOTE_CREDENTIALS

TO_REDACT = {"password", "secret_hash", "token", "ha1"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ShellyToolkitConfigEntry
) -> dict[str, Any]:
    """Return secret-free integration diagnostics."""
    runtime = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "devices": runtime.manager.list_devices(),
        "backups": runtime.repository.list(),
        "event_count": len(runtime.events.list(limit=500)),
        "local_target_count": len(entry.data.get(CONF_LOCAL_DEVICES, [])),
        "remote_credential_count": len(entry.data.get(CONF_REMOTE_CREDENTIALS, [])),
    }

