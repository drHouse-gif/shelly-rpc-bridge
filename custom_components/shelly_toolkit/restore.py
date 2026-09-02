"""Compatibility-aware, confirmed Shelly restore planning and execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from .backup import validate_backup
from .device_manager import DeviceManager
from .rpc import RpcError

NETWORK_NAMESPACES = {"wifi", "eth", "ws", "cloud", "mqtt", "sys"}
READ_ONLY_NAMESPACES = {
    "ble",
    "bluetooth",
    "devicepower",
    "em",
    "em1",
    "emdata",
    "humidity",
    "sys",
    "temperature",
    "wifi",
}


class RestoreStatus(StrEnum):
    """Restore preview/execution status."""

    READY = "READY"
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


@dataclass(slots=True)
class RestoreItem:
    """One previewed or executed operation."""

    category: str
    source: str
    status: RestoreStatus
    method: str | None = None
    params: dict[str, Any] | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-safe operation."""
        value = asdict(self)
        value["status"] = self.status.value
        return value


class RestoreEngine:
    """Build previews first and never factory-reset or restore connectivity."""

    def __init__(self, manager: DeviceManager) -> None:
        self.manager = manager

    async def async_preview(
        self, backup: dict[str, Any], target_id: str, *, mode: str = "smart"
    ) -> dict[str, Any]:
        """Analyze source/target compatibility without mutating the target."""
        validate_backup(backup)
        target = await self.manager.async_refresh_device(target_id)
        if not target.online:
            raise ValueError("Target device is offline")
        source_model = backup["device"].get("model")
        exact = source_model == target.model
        if mode == "exact" and not exact:
            raise ValueError("Exact clone requires the same advertised model")
        items: list[RestoreItem] = []
        target_components = target.capabilities.components
        raw_components = backup["configuration"].get("components", [])
        if isinstance(raw_components, list):
            for raw in raw_components:
                if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
                    continue
                key = raw["key"]
                namespace, _, component_id = key.partition(":")
                lowered = namespace.lower()
                if lowered in NETWORK_NAMESPACES:
                    items.append(
                        RestoreItem(
                            "component",
                            key,
                            RestoreStatus.SKIPPED,
                            reason="Network/auth/system configuration is never restored automatically",
                        )
                    )
                    continue
                config = raw.get("config")
                if not isinstance(config, dict):
                    continue
                if key not in target_components:
                    items.append(
                        RestoreItem(
                            "component",
                            key,
                            RestoreStatus.UNSUPPORTED,
                            reason="Target has no compatible component",
                        )
                    )
                    continue
                method = f"{namespace.upper() if lowered in {'rgb', 'rgbw'} else namespace.title()}.SetConfig"
                if method not in target.capabilities.methods and lowered in READ_ONLY_NAMESPACES:
                    items.append(
                        RestoreItem(
                            "component",
                            key,
                            RestoreStatus.UNSUPPORTED,
                            reason="Component is read-only or SetConfig is unavailable",
                        )
                    )
                    continue
                clean_config = {
                    field: value
                    for field, value in config.items()
                    if field not in {"id", "source"}
                }
                params: dict[str, Any] = {"config": clean_config}
                if component_id.isdigit():
                    params["id"] = int(component_id)
                items.append(
                    RestoreItem(
                        "component", key, RestoreStatus.READY, method=method, params=params
                    )
                )
        resources = backup["configuration"].get("resources", {})
        if isinstance(resources, dict):
            items.extend(self._plan_scripts(resources, target, exact))
            items.extend(self._plan_list_resource(resources, target, "schedules", "Schedule.Create"))
            items.extend(self._plan_list_resource(resources, target, "webhooks", "Webhook.Create"))
        return {
            "mode": "exact" if exact and mode == "exact" else "smart",
            "source_model": source_model,
            "target_model": target.model,
            "compatible_model": exact,
            "items": [item.as_dict() for item in items],
            "summary": _summary(items),
        }

    def _plan_scripts(
        self, resources: dict[str, Any], target: Any, exact: bool
    ) -> list[RestoreItem]:
        scripts = resources.get("scripts", [])
        if not isinstance(scripts, list):
            return []
        if "Script.PutCode" not in target.capabilities.methods:
            return [
                RestoreItem(
                    "script",
                    str(item.get("name", item.get("id", "script"))),
                    RestoreStatus.UNSUPPORTED,
                    reason="Target does not advertise Shelly Script upload",
                )
                for item in scripts
                if isinstance(item, dict)
            ]
        result: list[RestoreItem] = []
        for item in scripts:
            if not isinstance(item, dict) or not isinstance(item.get("code"), str):
                continue
            script_id = item.get("id")
            if exact and isinstance(script_id, int):
                result.append(
                    RestoreItem(
                        "script",
                        str(item.get("name", script_id)),
                        RestoreStatus.READY,
                        method="Script.PutCode",
                        params={"id": script_id, "code": item["code"], "append": False},
                    )
                )
            elif "Script.Create" in target.capabilities.methods:
                result.append(
                    RestoreItem(
                        "script",
                        str(item.get("name", "Migrated script")),
                        RestoreStatus.READY,
                        method="Script.CreateAndUpload",
                        params={"name": str(item.get("name", "Migrated script")), "code": item["code"]},
                    )
                )
            else:
                result.append(
                    RestoreItem(
                        "script",
                        str(item.get("name", "script")),
                        RestoreStatus.UNSUPPORTED,
                        reason="Target cannot create a script for smart migration",
                    )
                )
        return result

    @staticmethod
    def _plan_list_resource(
        resources: dict[str, Any], target: Any, key: str, method: str
    ) -> list[RestoreItem]:
        raw = resources.get(key)
        if not isinstance(raw, dict):
            return []
        aliases = {
            "schedules": ("schedules", "jobs"),
            "webhooks": ("webhooks", "hooks"),
        }
        values: Any = []
        for candidate in aliases.get(key, (key,)):
            if isinstance(raw.get(candidate), list):
                values = raw[candidate]
                break
        if not isinstance(values, list):
            return []
        if method not in target.capabilities.methods:
            return [
                RestoreItem(
                    key[:-1],
                    str(index),
                    RestoreStatus.UNSUPPORTED,
                    reason=f"Target does not advertise {method}",
                )
                for index, _ in enumerate(values)
            ]
        return [
            RestoreItem(
                key[:-1],
                str(item.get("id", index)) if isinstance(item, dict) else str(index),
                RestoreStatus.READY,
                method=method,
                params={k: v for k, v in item.items() if k not in {"id", "rev"}},
            )
            for index, item in enumerate(values)
            if isinstance(item, dict)
        ]

    async def async_apply(
        self,
        backup: dict[str, Any],
        target_id: str,
        *,
        mode: str,
        confirm: bool,
    ) -> dict[str, Any]:
        """Execute only READY preview operations after explicit confirmation."""
        if confirm is not True:
            raise ValueError("Explicit confirmation is required")
        preview = await self.async_preview(backup, target_id, mode=mode)
        results: list[RestoreItem] = []
        for raw in preview["items"]:
            item = RestoreItem(
                category=raw["category"],
                source=raw["source"],
                status=RestoreStatus(raw["status"]),
                method=raw.get("method"),
                params=raw.get("params"),
                reason=raw.get("reason"),
            )
            if item.status is not RestoreStatus.READY or item.method is None:
                results.append(item)
                continue
            try:
                if item.method == "Script.CreateAndUpload":
                    created = await self.manager.async_call(
                        target_id, "Script.Create", {"name": item.params["name"]}
                    )
                    await self.manager.async_call(
                        target_id,
                        "Script.PutCode",
                        {"id": int(created["id"]), "code": item.params["code"], "append": False},
                    )
                else:
                    await self.manager.async_call(target_id, item.method, item.params)
            except (RpcError, KeyError, TypeError, ValueError) as err:
                item.status = RestoreStatus.FAILED
                item.reason = f"{type(err).__name__}: {err}"
            else:
                item.status = RestoreStatus.SUCCESS
            results.append(item)
        return {
            "source_model": preview["source_model"],
            "target_model": preview["target_model"],
            "items": [item.as_dict() for item in results],
            "summary": _summary(results),
        }


def _summary(items: list[RestoreItem]) -> dict[str, int]:
    summary = {status.value: 0 for status in RestoreStatus}
    for item in items:
        summary[item.status.value] += 1
    return summary
