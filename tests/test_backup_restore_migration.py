"""Backup, restore, and migration safety tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from custom_components.shelly_toolkit.backup import (
    BACKUP_VERSION,
    BackupEngine,
    scrub_secrets,
    validate_backup,
)
from custom_components.shelly_toolkit.migration import MigrationEngine
from custom_components.shelly_toolkit.models import (
    CapabilitySet,
    ConnectionKind,
    ToolkitDevice,
)
from custom_components.shelly_toolkit.restore import RestoreEngine


class MemoryRepository:
    def __init__(self) -> None:
        self.values = []

    async def async_add(self, value) -> None:
        self.values.append(deepcopy(value))


class FakeManager:
    def __init__(self) -> None:
        self.calls = []
        self.source = ToolkitDevice(
            id="local:source",
            connection=ConnectionKind.LOCAL,
            name="Source",
            online=True,
            info={"model": "SNSW-001P16EU", "mac": "AABBCCDDEEFF", "gen": 2},
            config={"mqtt": {"enable": False, "password": "must-not-export"}},
            capabilities=CapabilitySet(
                components={"switch:0": {}, "wifi": {}},
                methods={
                    "Shelly.GetComponents",
                    "Switch.SetConfig",
                    "Schedule.List",
                    "Schedule.Create",
                },
            ),
        )
        self.target = ToolkitDevice(
            id="local:target",
            connection=ConnectionKind.LOCAL,
            name="Target",
            online=True,
            info={"model": "SNSW-001P16EU", "mac": "112233445566", "gen": 4},
            capabilities=CapabilitySet(
                components={"switch:0": {}, "wifi": {}},
                methods={"Switch.SetConfig", "Schedule.Create"},
            ),
        )

    async def async_refresh_device(self, device_id):
        return self.source if device_id == self.source.id else self.target

    def get_device(self, device_id):
        return self.source if device_id == self.source.id else self.target

    def get_transport(self, device_id):
        return self

    async def async_call(self, *args):
        if len(args) == 2 and isinstance(args[0], str) and "." in args[0]:
            method, params = args[0], args[1]
        else:
            _, method, *remaining = args
            params = remaining[0] if remaining else None
        self.calls.append((method, params))
        if method == "Shelly.GetComponents":
            return {
                "components": [
                    {"key": "switch:0", "config": {"id": 0, "name": "Pump"}},
                    {"key": "wifi", "config": {"ssid": "Lab", "pass": "hidden"}},
                ]
            }
        if method == "Schedule.List":
            return {"jobs": [{"id": 1, "timespec": "0 0 12 * * *", "calls": []}]}
        return {"ok": True}


def backup_fixture() -> dict:
    return {
        "toolkit_backup_version": BACKUP_VERSION,
        "id": "backup-one",
        "created_at": "2026-09-02T00:00:00+00:00",
        "device": {"id": "local:source", "name": "Source", "model": "SNSW-001P16EU"},
        "capabilities": {},
        "configuration": {
            "device": {},
            "components": [
                {"key": "switch:0", "config": {"id": 0, "name": "Pump"}},
                {"key": "wifi", "config": {"ssid": "Lab"}},
                {"key": "cover:0", "config": {"id": 0}},
            ],
            "resources": {
                "schedules": {"jobs": [{"id": 1, "timespec": "0 0 12 * * *", "calls": []}]}
            },
        },
        "redacted_paths": [],
    }


def test_secret_scrubbing_preserves_component_identifier() -> None:
    cleaned, redacted = scrub_secrets(
        {"components": [{"key": "switch:0", "config": {"pass": "x", "api_key": "y"}}]}
    )
    assert cleaned["components"][0]["key"] == "switch:0"
    assert cleaned["components"][0]["config"] == {}
    assert set(redacted) == {
        "components[0].config.api_key",
        "components[0].config.pass",
    }


async def test_backup_is_versioned_serializable_and_secret_free() -> None:
    manager = FakeManager()
    repository = MemoryRepository()
    backup = await BackupEngine(manager, repository).async_create(manager.source.id)
    validate_backup(backup)
    assert backup["toolkit_backup_version"] == 1
    assert backup["configuration"]["components"][0]["key"] == "switch:0"
    assert "password" not in str(backup)
    assert "hidden" not in str(backup)
    assert repository.values[0]["id"] == backup["id"]


async def test_restore_preview_and_confirmed_apply() -> None:
    manager = FakeManager()
    engine = RestoreEngine(manager)
    preview = await engine.async_preview(backup_fixture(), manager.target.id, mode="smart")
    statuses = {item["source"]: item["status"] for item in preview["items"]}
    assert statuses["switch:0"] == "READY"
    assert statuses["wifi"] == "SKIPPED"
    assert statuses["cover:0"] == "UNSUPPORTED"
    assert preview["summary"]["READY"] == 2
    with pytest.raises(ValueError, match="confirmation"):
        await engine.async_apply(backup_fixture(), manager.target.id, mode="smart", confirm=False)
    report = await engine.async_apply(
        backup_fixture(), manager.target.id, mode="smart", confirm=True
    )
    assert report["summary"]["SUCCESS"] == 2
    assert any(method == "Switch.SetConfig" for method, _ in manager.calls)


async def test_exact_clone_rejects_different_model() -> None:
    manager = FakeManager()
    backup = backup_fixture()
    backup["device"]["model"] = "different-model"
    with pytest.raises(ValueError, match="same advertised model"):
        await RestoreEngine(manager).async_preview(backup, manager.target.id, mode="exact")


async def test_migration_rejects_same_source_and_target() -> None:
    manager = FakeManager()
    repository = MemoryRepository()
    backups = BackupEngine(manager, repository)
    migration = MigrationEngine(backups, RestoreEngine(manager))
    with pytest.raises(ValueError, match="different"):
        await migration.async_preview(manager.source.id, manager.source.id)
