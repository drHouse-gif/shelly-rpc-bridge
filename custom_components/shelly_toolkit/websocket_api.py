"""Admin-only WebSocket API consumed by the Shelly Toolkit panel."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.network import get_url

from .backup import validate_backup
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_REMOTE_CREDENTIALS,
    CONF_TRANSPORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DATA_WS_REGISTERED,
    DESTRUCTIVE_RPC_METHODS,
    DOMAIN,
    MAX_RPC_PARAMS_BYTES,
    REMOTE_WS_PATH,
    TRANSPORT_HTTP,
    TRANSPORT_WEBSOCKET,
)
from .remote import new_remote_credential, normalize_credentials
from .rpc import validate_method
from .services import SCRIPT_ID


def _runtime(hass: HomeAssistant) -> Any:
    from . import get_runtime

    return get_runtime(hass)


def _validate_host(value: str) -> str:
    value = value.strip()
    if (
        not value
        or len(value) > 253
        or any(char in value for char in ("/", "@", "#", "?", " "))
        or "://" in value
    ):
        raise vol.Invalid("Enter only an IPv4 address or hostname")
    return value


def _validate_rpc_params(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value, separators=(",", ":")).encode()) > MAX_RPC_PARAMS_BYTES:
        raise vol.Invalid("RPC parameters exceed the safe size limit")
    return value


def _remote_url(hass: HomeAssistant, credential_id: str, secret: str) -> str:
    base = get_url(
        hass,
        allow_internal=True,
        allow_external=True,
        allow_cloud=True,
        prefer_external=True,
        prefer_cloud=True,
    )
    parsed = urlsplit(base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit(
        (
            scheme,
            parsed.netloc,
            REMOTE_WS_PATH,
            urlencode({"id": credential_id, "token": secret}),
            "",
        )
    )


async def _set_credentials(hass: HomeAssistant, credentials: list[dict[str, Any]]) -> None:
    runtime = _runtime(hass)
    data = deepcopy(dict(runtime.manager.entry.data))
    data[CONF_REMOTE_CREDENTIALS] = credentials
    hass.config_entries.async_update_entry(runtime.manager.entry, data=data)
    await runtime.manager.remote_server.async_update_credentials(credentials)


def _public_credentials(hass: HomeAssistant) -> list[dict[str, Any]]:
    runtime = _runtime(hass)
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "created_at": item["created_at"],
            "bound_device_id": item.get("bound_device_id"),
        }
        for item in normalize_credentials(
            runtime.manager.entry.data.get(CONF_REMOTE_CREDENTIALS, [])
        )
    ]


def _resolve_backup(runtime: Any, msg: dict[str, Any]) -> dict[str, Any]:
    if isinstance(msg.get("backup"), dict):
        return validate_backup(msg["backup"])
    if isinstance(msg.get("backup_id"), str):
        return runtime.repository.get(msg["backup_id"])
    raise ValueError("backup or backup_id is required")


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the panel backend exactly once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_WS_REGISTERED):
        return
    commands = (
        ws_overview,
        ws_devices,
        ws_refresh,
        ws_local_add,
        ws_local_remove,
        ws_credentials,
        ws_credential_create,
        ws_credential_revoke,
        ws_credential_regenerate,
        ws_rpc_call,
        ws_doctor,
        ws_backups,
        ws_backup_create,
        ws_backup_get,
        ws_backup_delete,
        ws_restore_preview,
        ws_restore_apply,
        ws_migration_preview,
        ws_migration_apply,
        ws_scripts,
        ws_script_code,
        ws_script_upload,
        ws_script_control,
        ws_events,
        ws_subscribe_events,
    )
    for command in commands:
        websocket_api.async_register_command(hass, command)
    domain_data[DATA_WS_REGISTERED] = True


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "shelly_toolkit/overview"})
@callback
def ws_overview(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    runtime = _runtime(hass)
    devices = runtime.manager.list_devices()
    reports = runtime.doctor.latest()
    problems = [
        {"device_id": report["device_id"], "name": report["name"], **finding}
        for report in reports
        for finding in report["findings"]
        if finding["severity"] in {"WARNING", "ERROR"}
    ]
    connection.send_result(
        msg["id"],
        {
            "total": len(devices),
            "online": sum(1 for item in devices if item["online"]),
            "remote": sum(1 for item in devices if item["connection"] == "remote"),
            "offline": sum(1 for item in devices if not item["online"]),
            "warnings": len(problems),
            "backups": len(runtime.repository.list()),
            "latest_problems": problems[-10:],
            "latest_events": runtime.events.list(limit=10),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "shelly_toolkit/devices"})
@callback
def ws_devices(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], _runtime(hass).manager.list_devices())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/refresh",
        vol.Optional("device_id"): str,
    }
)
@websocket_api.async_response
async def ws_refresh(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    runtime = _runtime(hass)
    if device_id := msg.get("device_id"):
        refreshed = await runtime.manager.async_refresh_device(device_id)
        result = next(item for item in runtime.manager.list_devices() if item["id"] == refreshed.id)
    else:
        result = await runtime.manager.async_refresh_all()
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/local/add",
        vol.Required(CONF_HOST): _validate_host,
        vol.Optional(CONF_PORT, default=80): cv.port,
        vol.Optional(CONF_USERNAME, default="admin"): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Optional(CONF_TRANSPORT, default=TRANSPORT_WEBSOCKET): vol.In(
            {TRANSPORT_HTTP, TRANSPORT_WEBSOCKET}
        ),
        vol.Optional("use_ssl", default=False): cv.boolean,
        vol.Optional(CONF_VERIFY_SSL, default=False): cv.boolean,
        vol.Optional("name"): str,
    }
)
@websocket_api.async_response
async def ws_local_add(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    config = {key: value for key, value in msg.items() if key not in {"id", "type"}}
    manager = _runtime(hass).manager
    device = await manager.async_add_local(config)
    result = next(item for item in manager.list_devices() if item["id"] == device.id)
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/local/remove",
        vol.Required("device_id"): str,
    }
)
@websocket_api.async_response
async def ws_local_remove(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    await _runtime(hass).manager.async_remove_local(msg["device_id"])
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "shelly_toolkit/credentials"})
@callback
def ws_credentials(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], _public_credentials(hass))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/credential/create",
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=80)),
    }
)
@websocket_api.async_response
async def ws_credential_create(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    record, secret = new_remote_credential(msg["name"])
    runtime = _runtime(hass)
    credentials = normalize_credentials(runtime.manager.entry.data.get(CONF_REMOTE_CREDENTIALS, []))
    credentials.append(record)
    await _set_credentials(hass, credentials)
    connection.send_result(
        msg["id"],
        {
            "credential": _public_credentials(hass)[-1],
            "url": _remote_url(hass, record["id"], secret),
            "secret_shown_once": True,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/credential/revoke",
        vol.Required("credential_id"): str,
        vol.Required("confirm"): vol.Equal(True),
    }
)
@websocket_api.async_response
async def ws_credential_revoke(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    runtime = _runtime(hass)
    credentials = [
        item
        for item in normalize_credentials(
            runtime.manager.entry.data.get(CONF_REMOTE_CREDENTIALS, [])
        )
        if item["id"] != msg["credential_id"]
    ]
    await _set_credentials(hass, credentials)
    connection.send_result(msg["id"], _public_credentials(hass))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/credential/regenerate",
        vol.Required("credential_id"): str,
        vol.Required("confirm"): vol.Equal(True),
    }
)
@websocket_api.async_response
async def ws_credential_regenerate(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    runtime = _runtime(hass)
    credentials = normalize_credentials(runtime.manager.entry.data.get(CONF_REMOTE_CREDENTIALS, []))
    target = next((item for item in credentials if item["id"] == msg["credential_id"]), None)
    if target is None:
        raise ValueError("Unknown credential")
    replacement, secret = new_remote_credential(target["name"])
    replacement["id"] = target["id"]
    credentials = [replacement if item["id"] == target["id"] else item for item in credentials]
    await _set_credentials(hass, credentials)
    connection.send_result(
        msg["id"],
        {
            "credential": next(
                item for item in _public_credentials(hass) if item["id"] == target["id"]
            ),
            "url": _remote_url(hass, replacement["id"], secret),
            "secret_shown_once": True,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/rpc",
        vol.Required("device_id"): str,
        vol.Required("method"): str,
        vol.Optional("params", default={}): vol.All(dict, _validate_rpc_params),
        vol.Optional("confirm", default=False): cv.boolean,
    }
)
@websocket_api.async_response
async def ws_rpc_call(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    method = validate_method(msg["method"])
    if method in DESTRUCTIVE_RPC_METHODS and msg["confirm"] is not True:
        raise ValueError("Destructive RPC requires explicit confirmation")
    result = await _runtime(hass).manager.async_call(msg["device_id"], method, msg["params"])
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "shelly_toolkit/doctor", vol.Required("device_id"): str}
)
@websocket_api.async_response
async def ws_doctor(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], await _runtime(hass).doctor.async_run(msg["device_id"]))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "shelly_toolkit/backups"})
@callback
def ws_backups(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], _runtime(hass).repository.list())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "shelly_toolkit/backup/create", vol.Required("device_id"): str}
)
@websocket_api.async_response
async def ws_backup_create(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], await _runtime(hass).backups.async_create(msg["device_id"]))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "shelly_toolkit/backup/get", vol.Required("backup_id"): str}
)
@callback
def ws_backup_get(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], _runtime(hass).repository.get(msg["backup_id"]))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/backup/delete",
        vol.Required("backup_id"): str,
        vol.Required("confirm"): vol.Equal(True),
    }
)
@websocket_api.async_response
async def ws_backup_delete(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    await _runtime(hass).repository.async_delete(msg["backup_id"])
    connection.send_result(msg["id"])


RESTORE_SCHEMA = {
    vol.Required("target_id"): str,
    vol.Optional("backup_id"): str,
    vol.Optional("backup"): dict,
    vol.Optional("mode", default="smart"): vol.In({"exact", "smart"}),
}


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "shelly_toolkit/restore/preview", **RESTORE_SCHEMA}
)
@websocket_api.async_response
async def ws_restore_preview(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    runtime = _runtime(hass)
    result = await runtime.restore.async_preview(
        _resolve_backup(runtime, msg), msg["target_id"], mode=msg["mode"]
    )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/restore/apply",
        **RESTORE_SCHEMA,
        vol.Required("confirm"): vol.Equal(True),
    }
)
@websocket_api.async_response
async def ws_restore_apply(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    runtime = _runtime(hass)
    result = await runtime.restore.async_apply(
        _resolve_backup(runtime, msg),
        msg["target_id"],
        mode=msg["mode"],
        confirm=msg["confirm"],
    )
    connection.send_result(msg["id"], result)


MIGRATION_SCHEMA = {
    vol.Required("source_id"): str,
    vol.Required("target_id"): str,
    vol.Optional("mode", default="smart"): vol.In({"exact", "smart"}),
}


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "shelly_toolkit/migration/preview", **MIGRATION_SCHEMA}
)
@websocket_api.async_response
async def ws_migration_preview(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    result = await _runtime(hass).migration.async_preview(
        msg["source_id"], msg["target_id"], mode=msg["mode"]
    )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/migration/apply",
        **MIGRATION_SCHEMA,
        vol.Required("confirm"): vol.Equal(True),
    }
)
@websocket_api.async_response
async def ws_migration_apply(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    result = await _runtime(hass).migration.async_apply(
        msg["source_id"],
        msg["target_id"],
        mode=msg["mode"],
        confirm=msg["confirm"],
    )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "shelly_toolkit/scripts", vol.Required("device_id"): str}
)
@websocket_api.async_response
async def ws_scripts(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], await _runtime(hass).scripts.async_list(msg["device_id"]))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/script/code",
        vol.Required("device_id"): str,
        vol.Required("script_id"): SCRIPT_ID,
    }
)
@websocket_api.async_response
async def ws_script_code(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    code = await _runtime(hass).scripts.async_get_code(msg["device_id"], msg["script_id"])
    connection.send_result(msg["id"], {"code": code})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/script/upload",
        vol.Required("device_id"): str,
        vol.Required("script_id"): SCRIPT_ID,
        vol.Required("code"): str,
        vol.Optional("name", default="Shelly Script"): str,
        vol.Required("confirm"): vol.Equal(True),
    }
)
@websocket_api.async_response
async def ws_script_upload(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    result = await _runtime(hass).scripts.async_upload(
        msg["device_id"], msg["script_id"], msg["code"], name=msg["name"]
    )
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/script/control",
        vol.Required("device_id"): str,
        vol.Required("script_id"): SCRIPT_ID,
        vol.Required("action"): vol.In({"start", "stop", "restart", "status"}),
    }
)
@websocket_api.async_response
async def ws_script_control(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    studio = _runtime(hass).scripts
    handler = getattr(studio, f"async_{msg['action']}")
    result = await handler(msg["device_id"], msg["script_id"])
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "shelly_toolkit/events",
        vol.Optional("device_id"): str,
        vol.Optional("filter"): str,
        vol.Optional("limit", default=200): vol.All(cv.positive_int, vol.Range(max=500)),
    }
)
@callback
def ws_events(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    connection.send_result(
        msg["id"],
        _runtime(hass).events.list(
            device_id=msg.get("device_id"),
            event_filter=msg.get("filter"),
            limit=msg["limit"],
        ),
    )


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "shelly_toolkit/events/subscribe"})
@callback
def ws_subscribe_events(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    unsubscribe = _runtime(hass).events.subscribe(
        lambda event: connection.send_event(msg["id"], event.as_dict())
    )
    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
