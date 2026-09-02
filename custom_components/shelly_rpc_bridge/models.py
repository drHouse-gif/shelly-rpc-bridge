"""Protocol-independent models for Shelly RPC Bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass(slots=True)
class RemoteComponent:
    """Last known config and status for one Shelly component."""

    key: str
    config: dict[str, Any] = field(default_factory=dict)
    status: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.key.split(":", 1)[0].lower()

    @property
    def component_id(self) -> int:
        try:
            return int(self.key.split(":", 1)[1])
        except (IndexError, ValueError):
            return 0


@dataclass(slots=True)
class RemoteDevice:
    """A Shelly device known by the relay."""

    device_id: str
    online: bool = False
    last_seen: float | None = None
    info: dict[str, Any] = field(default_factory=dict)
    components: dict[str, RemoteComponent] = field(default_factory=dict)

    @property
    def sleeping(self) -> bool:
        """Treat battery-powered devices as available between wake cycles."""
        return any(
            key.startswith(("devicepower:", "battery:")) for key in self.components
        )

    @property
    def available(self) -> bool:
        return self.online or self.sleeping

    def apply_snapshot(
        self,
        *,
        online: bool,
        last_seen: float | None,
        info: dict[str, Any],
        components: list[dict[str, Any]],
    ) -> None:
        self.online = online
        self.last_seen = last_seen
        if info:
            self.info.update(info)
        for raw in components:
            key = raw.get("key")
            if not isinstance(key, str):
                continue
            component = self.components.setdefault(key, RemoteComponent(key))
            config = raw.get("config")
            status = raw.get("status")
            if isinstance(config, dict):
                component.config.update(config)
            if isinstance(status, dict):
                component.status.update(status)

    def apply_rpc_frame(self, frame: dict[str, Any]) -> bool:
        """Apply Shelly notifications; return True if entity state changed."""
        method = frame.get("method")
        params = frame.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return False

        target = "config" if method in {"NotifyConfig", "NotifyFullConfig"} else "status"
        if method not in {
            "NotifyStatus",
            "NotifyFullStatus",
            "NotifyConfig",
            "NotifyFullConfig",
        }:
            return False

        changed = False
        for key, value in params.items():
            if key in {"ts", "rev"} or not isinstance(value, dict):
                continue
            component = self.components.setdefault(key, RemoteComponent(key))
            destination = component.config if target == "config" else component.status
            destination.update(value)
            changed = True
        return changed


def flatten_scalars(
    value: dict[str, Any], prefix: tuple[str, ...] = (), max_depth: int = 3
) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Yield scalar paths from a nested status object."""
    if len(prefix) >= max_depth:
        return
    for key, child in value.items():
        path = (*prefix, str(key))
        if isinstance(child, dict):
            yield from flatten_scalars(child, path, max_depth)
        elif isinstance(child, (str, int, float, bool)) or child is None:
            yield path, child


def value_at_path(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Read a previously flattened path."""
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
