"""Exact clone and capability-based smart migration orchestration."""

from __future__ import annotations

from typing import Any

from .backup import BackupEngine
from .restore import RestoreEngine


class MigrationEngine:
    """Clone configuration through a sanitized logical backup."""

    def __init__(self, backups: BackupEngine, restore: RestoreEngine) -> None:
        self.backups = backups
        self.restore = restore

    async def async_preview(
        self, source_id: str, target_id: str, *, mode: str = "smart"
    ) -> dict[str, Any]:
        """Create an ephemeral source snapshot and return target preview."""
        if source_id == target_id:
            raise ValueError("Source and target must be different")
        backup = await self.backups.async_create(source_id, persist=False)
        result = await self.restore.async_preview(backup, target_id, mode=mode)
        result["source_id"] = source_id
        result["target_id"] = target_id
        result["backup"] = backup
        return result

    async def async_apply(
        self,
        source_id: str,
        target_id: str,
        *,
        mode: str,
        confirm: bool,
    ) -> dict[str, Any]:
        """Re-capture source and apply the confirmed migration plan."""
        if source_id == target_id:
            raise ValueError("Source and target must be different")
        backup = await self.backups.async_create(source_id, persist=True)
        return await self.restore.async_apply(backup, target_id, mode=mode, confirm=confirm)
