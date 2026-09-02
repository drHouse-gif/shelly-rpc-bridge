"""Reliable Shelly Script lifecycle management."""

from __future__ import annotations

from typing import Any

from .backup import BackupEngine, async_read_script_code
from .device_manager import DeviceManager

MAX_SCRIPT_BYTES = 256_000
PUT_CHUNK_BYTES = 4_096


class ScriptStudio:
    """List, inspect, upload, and control Shelly Scripts."""

    def __init__(self, manager: DeviceManager, backups: BackupEngine) -> None:
        self.manager = manager
        self.backups = backups

    async def async_list(self, device_id: str) -> list[dict[str, Any]]:
        """Return script list enriched with individual status."""
        result = await self.manager.async_call(device_id, "Script.List")
        scripts = result.get("scripts", [])
        if not isinstance(scripts, list):
            return []
        output: list[dict[str, Any]] = []
        for item in scripts:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                continue
            record = dict(item)
            try:
                record["status"] = await self.manager.async_call(
                    device_id, "Script.GetStatus", {"id": item["id"]}
                )
            except Exception as err:
                record["status_error"] = type(err).__name__
            output.append(record)
        return output

    async def async_get_code(self, device_id: str, script_id: int) -> str:
        """Get complete script code."""
        return await async_read_script_code(self.manager, device_id, script_id)

    async def async_upload(
        self,
        device_id: str,
        script_id: int,
        code: str,
        *,
        name: str = "Shelly Script",
    ) -> dict[str, Any]:
        """Back up old code, then upload verified UTF-8 chunks."""
        encoded = code.encode()
        if len(encoded) > MAX_SCRIPT_BYTES:
            raise ValueError("Script exceeds Toolkit's safe upload limit")
        previous = await self.async_get_code(device_id, script_id)
        backup = await self.backups.async_create_script_backup(
            device_id, script_id, name, previous
        )
        chunks = _utf8_chunks(code, PUT_CHUNK_BYTES)
        for index, chunk in enumerate(chunks):
            await self.manager.async_call(
                device_id,
                "Script.PutCode",
                {"id": script_id, "code": chunk, "append": index > 0},
            )
        return {
            "backup_id": backup["id"],
            "script_id": script_id,
            "bytes": len(encoded),
            "chunks": len(chunks),
        }

    async def async_start(self, device_id: str, script_id: int) -> dict[str, Any]:
        return await self.manager.async_call(device_id, "Script.Start", {"id": script_id})

    async def async_stop(self, device_id: str, script_id: int) -> dict[str, Any]:
        return await self.manager.async_call(device_id, "Script.Stop", {"id": script_id})

    async def async_restart(self, device_id: str, script_id: int) -> dict[str, Any]:
        await self.async_stop(device_id, script_id)
        return await self.async_start(device_id, script_id)

    async def async_status(self, device_id: str, script_id: int) -> dict[str, Any]:
        """Return status and real API-provided errors; Shelly has no generic log RPC."""
        return await self.manager.async_call(
            device_id, "Script.GetStatus", {"id": script_id}
        )


def _utf8_chunks(value: str, byte_limit: int) -> list[str]:
    """Split text without cutting a multi-byte UTF-8 code point."""
    if byte_limit < 4:
        raise ValueError("UTF-8 chunk limit must be at least four bytes")
    if not value:
        return [""]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for character in value:
        char_size = len(character.encode("utf-8"))
        if current and size + char_size > byte_limit:
            chunks.append("".join(current))
            current = []
            size = 0
        current.append(character)
        size += char_size
    if current:
        chunks.append("".join(current))
    return chunks
