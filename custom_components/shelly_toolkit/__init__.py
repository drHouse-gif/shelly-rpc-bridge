"""Shelly Toolkit for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .backup import BackupEngine, BackupRepository
from .const import (
    CONF_LOCAL_DEVICES,
    CONF_REMOTE_CREDENTIALS,
    DATA_PANEL_REGISTERED,
    DATA_REMOTE_SERVER,
    DOMAIN,
    PANEL_URL,
    STATIC_URL,
)
from .coordinator import ToolkitCoordinator
from .device_manager import DeviceManager
from .doctor import ShellyDoctor
from .events import EventStore
from .migration import MigrationEngine
from .remote import RemoteReceiverView, RemoteServer
from .restore import RestoreEngine
from .scripts import ScriptStudio
from .services import async_setup_services
from .websocket_api import async_register_websocket_commands

type ShellyToolkitConfigEntry = ConfigEntry["ToolkitRuntime"]


@dataclass(slots=True)
class ToolkitRuntime:
    """Loaded integration services."""

    manager: DeviceManager
    coordinator: ToolkitCoordinator
    repository: BackupRepository
    backups: BackupEngine
    restore: RestoreEngine
    migration: MigrationEngine
    scripts: ScriptStudio
    doctor: ShellyDoctor
    events: EventStore


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions, WebSocket API, and the remote receiver once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if DATA_REMOTE_SERVER not in domain_data:
        server = RemoteServer()
        domain_data[DATA_REMOTE_SERVER] = server
        hass.http.register_view(RemoteReceiverView(server))
    async_setup_services(hass)
    async_register_websocket_commands(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ShellyToolkitConfigEntry
) -> bool:
    """Set up the single Toolkit hub."""
    server: RemoteServer = hass.data[DOMAIN][DATA_REMOTE_SERVER]
    events = EventStore()
    repository = BackupRepository(hass)
    await repository.async_load()
    manager = DeviceManager(hass, entry, server, events)
    await manager.async_start()
    coordinator = ToolkitCoordinator(hass, entry, manager)
    backups = BackupEngine(manager, repository)
    restore = RestoreEngine(manager)
    runtime = ToolkitRuntime(
        manager=manager,
        coordinator=coordinator,
        repository=repository,
        backups=backups,
        restore=restore,
        migration=MigrationEngine(backups, restore),
        scripts=ScriptStudio(manager, backups),
        doctor=ShellyDoctor(manager),
        events=events,
    )
    entry.runtime_data = runtime
    await coordinator.async_config_entry_first_refresh()
    await _async_register_panel(hass)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ShellyToolkitConfigEntry
) -> bool:
    """Unload sockets and sidebar panel cleanly."""
    await entry.runtime_data.coordinator.async_shutdown()
    await entry.runtime_data.manager.async_close()
    server: RemoteServer = hass.data[DOMAIN][DATA_REMOTE_SERVER]
    await server.async_update_credentials([])
    if hass.data[DOMAIN].get(DATA_PANEL_REGISTERED):
        frontend.async_remove_panel(hass, PANEL_URL, warn_if_unknown=False)
        hass.data[DOMAIN][DATA_PANEL_REGISTERED] = False
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Normalize early Toolkit config-entry schemas."""
    if entry.version > 1:
        return False
    data = dict(entry.data)
    data.setdefault(CONF_LOCAL_DEVICES, [])
    data.setdefault(CONF_REMOTE_CREDENTIALS, [])
    hass.config_entries.async_update_entry(entry, data=data, version=1, minor_version=0)
    return True


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Register the dependency-free, admin-only custom panel."""
    if hass.data[DOMAIN].get(DATA_PANEL_REGISTERED):
        return
    frontend_dir = Path(__file__).parent / "frontend"
    static_registered = hass.data[DOMAIN].get("static_registered", False)
    if not static_registered:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(frontend_dir), cache_headers=False)]
        )
        hass.data[DOMAIN]["static_registered"] = True
    await panel_custom.async_register_panel(
        hass=hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name="shelly-toolkit-panel",
        sidebar_title="Shelly Toolkit",
        sidebar_icon="mdi:tools",
        module_url=f"{STATIC_URL}/shelly-toolkit-panel.js",
        embed_iframe=False,
        trust_external=False,
        require_admin=True,
        handle_safe_area=True,
    )
    hass.data[DOMAIN][DATA_PANEL_REGISTERED] = True


def get_runtime(hass: HomeAssistant) -> ToolkitRuntime:
    """Return the one loaded runtime or raise a useful error."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise RuntimeError("Shelly Toolkit is not configured or loaded")
    return entries[0].runtime_data
