"""Protocol-independent Shelly Toolkit models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time
from typing import Any


class ConnectionKind(StrEnum):
    """How a target is reached."""

    LOCAL = "local"
    REMOTE = "remote"
    OFFICIAL = "official"


@dataclass(slots=True)
class CapabilitySet:
    """Runtime-discovered Shelly capabilities."""

    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    methods: set[str] = field(default_factory=set)
    namespaces: set[str] = field(default_factory=set)
    discovered_at: float | None = None

    def supports(self, method: str) -> bool:
        """Return whether a method is known to be supported."""
        return method in self.methods

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-safe representation."""
        return {
            "components": self.components,
            "methods": sorted(self.methods),
            "namespaces": sorted(self.namespaces),
            "discovered_at": self.discovered_at,
        }


@dataclass(slots=True)
class ToolkitDevice:
    """A unified local, remote, or official Shelly target."""

    id: str
    connection: ConnectionKind
    name: str
    host: str | None = None
    port: int | None = None
    online: bool = False
    last_seen: float | None = None
    info: dict[str, Any] = field(default_factory=dict)
    status: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    capabilities: CapabilitySet = field(default_factory=CapabilitySet)
    rpc_metrics: dict[str, Any] = field(
        default_factory=lambda: {
            "calls": 0,
            "failures": 0,
            "consecutive_failures": 0,
            "recent_failures": [],
        }
    )
    last_error: str | None = None
    registry_device_id: str | None = None

    def mark_seen(self) -> None:
        """Mark the device online."""
        self.online = True
        self.last_seen = time.time()
        self.last_error = None

    def record_rpc_success(self) -> None:
        """Record a successful logical RPC cycle."""
        self.rpc_metrics["calls"] += 1
        self.rpc_metrics["consecutive_failures"] = 0
        self.rpc_metrics["last_success"] = time.time()

    def record_rpc_failure(self) -> None:
        """Record a failure and retain only a 15-minute instability window."""
        now = time.time()
        self.rpc_metrics["calls"] += 1
        self.rpc_metrics["failures"] += 1
        self.rpc_metrics["consecutive_failures"] += 1
        recent = [
            value
            for value in self.rpc_metrics.get("recent_failures", [])
            if isinstance(value, (int, float)) and value >= now - 900
        ]
        recent.append(now)
        self.rpc_metrics["recent_failures"] = recent[-20:]
        self.rpc_metrics["last_failure"] = now

    @property
    def model(self) -> str | None:
        """Return advertised model."""
        value = self.info.get("model") or self.info.get("app")
        return str(value) if value is not None else None

    @property
    def mac(self) -> str | None:
        """Return normalized primary MAC when available."""
        value = self.info.get("mac")
        if not isinstance(value, str):
            return None
        return "".join(char for char in value if char.isalnum()).upper()

    @property
    def firmware(self) -> str | None:
        """Return advertised firmware version."""
        value = self.info.get("ver") or self.info.get("fw_id")
        return str(value) if value is not None else None

    def as_dict(self) -> dict[str, Any]:
        """Return panel-safe representation."""
        sys_status = self.status.get("sys", {})
        wifi_status = self.status.get("wifi", {})
        temperature = max(_temperatures(self.status), default=None)
        return {
            "id": self.id,
            "name": self.name,
            "model": self.model,
            "mac": self.mac,
            "firmware": self.firmware,
            "host": self.host,
            "port": self.port,
            "connection": self.connection.value,
            "online": self.online,
            "last_seen": self.last_seen,
            "uptime": sys_status.get("uptime") if isinstance(sys_status, dict) else None,
            "rssi": wifi_status.get("rssi") if isinstance(wifi_status, dict) else None,
            "temperature": temperature,
            "rpc_available": self.online and self.last_error is None,
            "rpc_metrics": self.rpc_metrics,
            "last_error": self.last_error,
            "capabilities": self.capabilities.as_dict(),
            "registry_device_id": self.registry_device_id,
        }


def _temperatures(status: dict[str, Any]) -> list[float]:
    """Extract real Celsius values from system and component status objects."""
    values: list[float] = []
    for key, raw in status.items():
        if not isinstance(raw, dict):
            continue
        temperature = raw.get("temperature")
        if isinstance(temperature, dict):
            temperature = temperature.get("tC")
        if temperature is None and key.startswith("temperature:"):
            temperature = raw.get("tC")
        if isinstance(temperature, (int, float)):
            values.append(float(temperature))
    return values


@dataclass(slots=True, frozen=True)
class RpcEvent:
    """One bounded RPC notification/event record."""

    timestamp: float
    device_id: str
    component: str | None
    event: str
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-safe representation."""
        return {
            "timestamp": self.timestamp,
            "device_id": self.device_id,
            "component": self.component,
            "event": self.event,
            "payload": self.payload,
        }
