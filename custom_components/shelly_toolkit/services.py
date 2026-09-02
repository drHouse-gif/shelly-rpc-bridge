"""Administrator-only Home Assistant actions for Shelly Toolkit."""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .const import (
    DESTRUCTIVE_RPC_METHODS,
    DOMAIN,
    MAX_RPC_PARAMS_BYTES,
)
from .rpc import validate_method

ATTR_DEVICE_ID = "device_id"
ATTR_SOURCE_DEVICE_ID = "source_device_id"
ATTR_TARGET_DEVICE_ID = "target_device_id"
ATTR_METHOD = "method"
ATTR_PARAMS = "params"
ATTR_CONFIRM = "confirm"
ATTR_BACKUP_ID = "backup_id"
ATTR_MODE = "mode"
ATTR_SCRIPT_ID = "script_id"

DEVICE_ID = vol.All(str, vol.Length(min=3, max=160))
MODE = vol.In({"exact", "smart"})


def _validate_params(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value, separators=(",", ":")).encode()) > MAX_RPC_PARAMS_BYTES:
        raise vol.Invalid("RPC params exceed safe size")
    return value


RPC_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): DEVICE_ID,
        vol.Required(ATTR_METHOD): str,
        vol.Optional(ATTR_PARAMS, default={}): vol.All(dict, _validate_params),
        vol.Optional(ATTR_CONFIRM, default=False): cv.boolean,
    }
)
DIAGNOSTICS_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): DEVICE_ID})
BACKUP_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): DEVICE_ID})
RESTORE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BACKUP_ID): str,
        vol.Required(ATTR_TARGET_DEVICE_ID): DEVICE_ID,
        vol.Optional(ATTR_MODE, default="smart"): MODE,
        vol.Required(ATTR_CONFIRM): vol.Equal(True),
    }
)
CLONE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SOURCE_DEVICE_ID): DEVICE_ID,
        vol.Required(ATTR_TARGET_DEVICE_ID): DEVICE_ID,
        vol.Optional(ATTR_MODE, default="smart"): MODE,
        vol.Required(ATTR_CONFIRM): vol.Equal(True),
    }
)
RESTART_SCRIPT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): DEVICE_ID,
        vol.Required(ATTR_SCRIPT_ID): cv.positive_int,
    }
)


def _runtime(hass: HomeAssistant) -> Any:
    from . import get_runtime

    return get_runtime(hass)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register every action during integration setup as required by HA."""

    async def handle_rpc(call: ServiceCall) -> dict[str, Any]:
        method = validate_method(call.data[ATTR_METHOD])
        if method in DESTRUCTIVE_RPC_METHODS and call.data[ATTR_CONFIRM] is not True:
            raise ValueError("Destructive RPC requires confirm: true")
        result = await _runtime(hass).manager.async_call(
            call.data[ATTR_DEVICE_ID], method, call.data[ATTR_PARAMS]
        )
        return {"result": result}

    async def handle_diagnostics(call: ServiceCall) -> dict[str, Any]:
        return await _runtime(hass).doctor.async_run(call.data[ATTR_DEVICE_ID])

    async def handle_backup(call: ServiceCall) -> dict[str, Any]:
        return await _runtime(hass).backups.async_create(call.data[ATTR_DEVICE_ID])

    async def handle_restore(call: ServiceCall) -> dict[str, Any]:
        runtime = _runtime(hass)
        backup = runtime.repository.get(call.data[ATTR_BACKUP_ID])
        return await runtime.restore.async_apply(
            backup,
            call.data[ATTR_TARGET_DEVICE_ID],
            mode=call.data[ATTR_MODE],
            confirm=call.data[ATTR_CONFIRM],
        )

    async def handle_clone(call: ServiceCall) -> dict[str, Any]:
        return await _runtime(hass).migration.async_apply(
            call.data[ATTR_SOURCE_DEVICE_ID],
            call.data[ATTR_TARGET_DEVICE_ID],
            mode=call.data[ATTR_MODE],
            confirm=call.data[ATTR_CONFIRM],
        )

    async def handle_restart_script(call: ServiceCall) -> dict[str, Any]:
        return await _runtime(hass).scripts.async_restart(
            call.data[ATTR_DEVICE_ID], call.data[ATTR_SCRIPT_ID]
        )

    async_register_admin_service(
        hass,
        DOMAIN,
        "rpc_call",
        handle_rpc,
        schema=RPC_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        "run_diagnostics",
        handle_diagnostics,
        schema=DIAGNOSTICS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        "backup_device",
        handle_backup,
        schema=BACKUP_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        "restore_device",
        handle_restore,
        schema=RESTORE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        "clone_device",
        handle_clone,
        schema=CLONE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        "restart_script",
        handle_restart_script,
        schema=RESTART_SCRIPT_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
