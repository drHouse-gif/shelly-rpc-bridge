"""Reliable Shelly Script lifecycle management."""

from __future__ import annotations

from typing import Any

from .backup import BackupEngine, async_read_script_code
from .device_manager import DeviceManager
from .rpc import RpcProtocolError

MAX_SCRIPT_BYTES = 256_000
PUT_CHUNK_BYTES = 1_024


class ScriptStudio:
    """List, inspect, upload, and control Shelly Scripts."""

    def __init__(self, manager: DeviceManager, backups: BackupEngine) -> None:
        self.manager = manager
        self.backups = backups

    async def async_list(self, device_id: str) -> list[dict[str, Any]]:
        """Return script list enriched with individual status."""
        result = await self.manager.async_call(device_id, "Script.List")
        if not isinstance(result, dict):
            raise RpcProtocolError("Script.List returned an invalid response")
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
        if not encoded:
            raise ValueError("Shelly Script code cannot be empty")
        if len(encoded) > MAX_SCRIPT_BYTES:
            raise ValueError("Script exceeds Toolkit's safe upload limit")
        previous = await self.async_get_code(device_id, script_id)
        backup = await self.backups.async_create_script_backup(device_id, script_id, name, previous)
        status = await self.async_status(device_id, script_id)
        was_running = status.get("running") is True
        if was_running:
            await self.async_stop(device_id, script_id)
        try:
            chunks = await async_put_script_code(self.manager, device_id, script_id, code)
        finally:
            if was_running:
                await self.async_start(device_id, script_id)
        return {
            "backup_id": backup["id"],
            "script_id": script_id,
            "bytes": len(encoded),
            "chunks": len(chunks),
            "restarted": was_running,
        }

    async def async_start(self, device_id: str, script_id: int) -> Any:
        return await self.manager.async_call(device_id, "Script.Start", {"id": script_id})

    async def async_stop(self, device_id: str, script_id: int) -> Any:
        return await self.manager.async_call(device_id, "Script.Stop", {"id": script_id})

    async def async_restart(self, device_id: str, script_id: int) -> Any:
        await self.async_stop(device_id, script_id)
        return await self.async_start(device_id, script_id)

    async def async_status(self, device_id: str, script_id: int) -> dict[str, Any]:
        """Return status and real API-provided errors; Shelly has no generic log RPC."""
        result = await self.manager.async_call(device_id, "Script.GetStatus", {"id": script_id})
        if not isinstance(result, dict):
            raise RpcProtocolError("Script.GetStatus returned an invalid response")
        return result


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


async def async_put_script_code(
    manager: DeviceManager,
    device_id: str,
    script_id: int,
    code: str,
    *,
    manage_running: bool = False,
) -> list[str]:
    """Upload non-empty Shelly Script code in documented 1024-byte chunks."""
    if not code:
        raise ValueError("Shelly Script code cannot be empty")
    was_running = False
    if manage_running:
        status = await manager.async_call(device_id, "Script.GetStatus", {"id": script_id})
        if not isinstance(status, dict):
            raise RpcProtocolError("Script.GetStatus returned an invalid response")
        was_running = status.get("running") is True
        if was_running:
            await manager.async_call(device_id, "Script.Stop", {"id": script_id})
    chunks = _utf8_chunks(code, PUT_CHUNK_BYTES)
    try:
        for index, chunk in enumerate(chunks):
            await manager.async_call(
                device_id,
                "Script.PutCode",
                {"id": script_id, "code": chunk, "append": index > 0},
            )
    finally:
        if was_running:
            await manager.async_call(device_id, "Script.Start", {"id": script_id})
    return chunks
