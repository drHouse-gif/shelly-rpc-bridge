"""Home Assistant downloadable diagnostics with mandatory redaction."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ShellyToolkitConfigEntry
from .backup import scrub_secrets
from .const import CONF_LOCAL_DEVICES, CONF_REMOTE_CREDENTIALS, SECRET_KEYS

TO_REDACT = set(SECRET_KEYS) | {"secret_hash"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ShellyToolkitConfigEntry
) -> dict[str, Any]:
    """Return secret-free integration diagnostics."""
    runtime = entry.runtime_data
    devices, _ = scrub_secrets(runtime.manager.list_devices())
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "devices": devices,
        "backups": runtime.repository.list(),
        "event_count": len(runtime.events.list(limit=500)),
        "local_target_count": len(entry.data.get(CONF_LOCAL_DEVICES, [])),
        "remote_credential_count": len(entry.data.get(CONF_REMOTE_CREDENTIALS, [])),
    }
