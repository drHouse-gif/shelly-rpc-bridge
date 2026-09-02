"""Versioned, secret-safe Shelly configuration backups."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
import secrets
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .capabilities import async_get_all_components
from .const import (
    DOMAIN,
    MAX_BACKUP_BYTES,
    MAX_BACKUPS,
    SECRET_KEYS,
)
from .device_manager import DeviceManager
from .rpc import RpcError, RpcProtocolError

BACKUP_VERSION = 1
STORE_VERSION = 1
STORE_KEY = f"{DOMAIN}.backups"


def scrub_secrets(value: Any, path: str = "") -> tuple[Any, list[str]]:
    """Recursively omit secret-like fields and return their JSON paths."""
    redacted: list[str] = []
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}" if path else key
            lowered = key.lower()
            component_identifier = lowered == "key" and path.startswith("components[")
            if not component_identifier and (
                lowered in SECRET_KEYS
                or any(
                    marker in lowered
                    for marker in (
                        "password",
                        "passwd",
                        "passphrase",
                        "token",
                        "secret",
                        "ha1",
                    )
                )
            ):
                redacted.append(child_path)
                continue
            sanitized, child_redacted = scrub_secrets(child, child_path)
            cleaned[key] = sanitized
            redacted.extend(child_redacted)
        return cleaned, redacted
    if isinstance(value, list):
        cleaned_list: list[Any] = []
        for index, child in enumerate(value):
            sanitized, child_redacted = scrub_secrets(child, f"{path}[{index}]")
            cleaned_list.append(sanitized)
            redacted.extend(child_redacted)
        return cleaned_list, redacted
    return deepcopy(value), redacted


def validate_backup(value: Any) -> dict[str, Any]:
    """Validate the stable outer backup schema and size."""
    if not isinstance(value, dict):
        raise ValueError("Backup must be a JSON object")
    if value.get("toolkit_backup_version") != BACKUP_VERSION:
        raise ValueError("Unsupported Shelly Toolkit backup version")
    if not isinstance(value.get("device"), dict):
        raise ValueError("Backup is missing source device information")
    if not isinstance(value.get("configuration"), dict):
        raise ValueError("Backup is missing configuration")
    if len(json.dumps(value, separators=(",", ":")).encode()) > MAX_BACKUP_BYTES:
        raise ValueError("Backup exceeds the safe size limit")
    return value


class BackupRepository:
    """Persist bounded backups through Home Assistant storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store[list[dict[str, Any]]](hass, STORE_VERSION, STORE_KEY)
        self._backups: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        """Load valid records, ignoring corrupted storage entries."""
        stored = await self._store.async_load()
        if isinstance(stored, list):
            for value in stored:
                try:
                    self._backups.append(validate_backup(value))
                except ValueError:
                    continue
        self._backups = self._backups[-MAX_BACKUPS:]

    async def async_add(self, backup: dict[str, Any]) -> None:
        """Add and persist one validated backup."""
        validate_backup(backup)
        self._backups.append(backup)
        self._backups = self._backups[-MAX_BACKUPS:]
        await self._store.async_save(self._backups)

    def get(self, backup_id: str) -> dict[str, Any]:
        """Return a deep copy of one backup."""
        for backup in self._backups:
            if backup.get("id") == backup_id:
                return deepcopy(backup)
        raise KeyError(backup_id)

    def list(self) -> list[dict[str, Any]]:
        """Return metadata without large configuration payloads."""
        return [
            {
                "id": item["id"],
                "created_at": item["created_at"],
                "device": item["device"],
                "kind": item.get("kind", "device"),
                "redacted_count": len(item.get("redacted_paths", [])),
            }
            for item in reversed(self._backups)
        ]

    async def async_delete(self, backup_id: str) -> None:
        """Delete one backup."""
        original = len(self._backups)
        self._backups = [item for item in self._backups if item.get("id") != backup_id]
        if len(self._backups) == original:
            raise KeyError(backup_id)
        await self._store.async_save(self._backups)


class BackupEngine:
    """Capture the maximum safely readable configuration from a device."""

    def __init__(self, manager: DeviceManager, repository: BackupRepository) -> None:
        self.manager = manager
        self.repository = repository

    async def async_create(
        self, device_id: str, *, persist: bool = True
    ) -> dict[str, Any]:
        """Create a full versioned backup."""
        device = await self.manager.async_refresh_device(device_id)
        if not device.online:
            raise ValueError("Cannot back up an offline device")
        transport = self.manager.get_transport(device_id)
        components = await async_get_all_components(transport)
        resources: dict[str, Any] = {}
        methods = device.capabilities.methods
        if "Script.List" in methods:
            resources["scripts"] = await self._read_scripts(device_id)
        for method, key in (("Schedule.List", "schedules"), ("Webhook.List", "webhooks")):
            if method in methods:
                try:
                    resources[key] = await self.manager.async_call(device_id, method)
                except RpcError as err:
                    resources[key] = {"error": type(err).__name__}
        raw_configuration = {
            "device": device.config,
            "components": components.get("components", []),
            "resources": resources,
        }
        configuration, redacted = scrub_secrets(raw_configuration)
        backup = {
            "toolkit_backup_version": BACKUP_VERSION,
            "id": secrets.token_hex(12),
            "kind": "device",
            "created_at": datetime.now(UTC).isoformat(),
            "device": {
                "id": device.id,
                "name": device.name,
                "model": device.model,
                "mac": device.mac,
                "firmware": device.firmware,
                "connection": device.connection.value,
            },
            "capabilities": device.capabilities.as_dict(),
            "configuration": configuration,
            "redacted_paths": sorted(redacted),
        }
        validate_backup(backup)
        if persist:
            await self.repository.async_add(backup)
        return backup

    async def async_create_script_backup(
        self, device_id: str, script_id: int, name: str, code: str
    ) -> dict[str, Any]:
        """Persist a small backup immediately before script overwrite."""
        device = self.manager.get_device(device_id)
        backup = {
            "toolkit_backup_version": BACKUP_VERSION,
            "id": secrets.token_hex(12),
            "kind": "script",
            "created_at": datetime.now(UTC).isoformat(),
            "device": {
                "id": device.id,
                "name": device.name,
                "model": device.model,
                "mac": device.mac,
                "firmware": device.firmware,
                "connection": device.connection.value,
            },
            "capabilities": device.capabilities.as_dict(),
            "configuration": {
                "device": {},
                "components": [],
                "resources": {
                    "scripts": [{"id": script_id, "name": name, "code": code}]
                },
            },
            "redacted_paths": [],
        }
        await self.repository.async_add(backup)
        return backup

    async def _read_scripts(self, device_id: str) -> list[dict[str, Any]]:
        result = await self.manager.async_call(device_id, "Script.List")
        if not isinstance(result, dict):
            raise RpcProtocolError("Script.List returned an invalid response")
        scripts = result.get("scripts", [])
        output: list[dict[str, Any]] = []
        if not isinstance(scripts, list):
            return output
        for item in scripts:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                continue
            record = dict(item)
            try:
                record["code"] = await async_read_script_code(
                    self.manager, device_id, item["id"]
                )
            except RpcError as err:
                record["code_error"] = type(err).__name__
            output.append(record)
        return output


async def async_read_script_code(
    manager: DeviceManager, device_id: str, script_id: int
) -> str:
    """Read potentially chunked Script.GetCode output."""
    chunks: list[str] = []
    offset = 0
    for _ in range(256):
        result = await manager.async_call(
            device_id, "Script.GetCode", {"id": script_id, "offset": offset}
        )
        if not isinstance(result, dict):
            raise RpcProtocolError("Script.GetCode returned an invalid response")
        data = result.get("data", result.get("code", ""))
        if not isinstance(data, str):
            raise ValueError("Script.GetCode returned invalid data")
        chunks.append(data)
        offset += len(data.encode())
        left = result.get("left", 0)
        if not isinstance(left, int) or left <= 0:
            return "".join(chunks)
    raise ValueError("Script.GetCode exceeded chunk limit")
