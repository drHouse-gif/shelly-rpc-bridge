"""Bounded Shelly RPC event collection."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import time
from typing import Any

from .models import RpcEvent


class EventStore:
    """Keep a bounded in-memory event history."""

    def __init__(self, maxlen: int = 500) -> None:
        self._events: deque[RpcEvent] = deque(maxlen=maxlen)
        self._listeners: set[Callable[[RpcEvent], None]] = set()

    def add_frame(self, device_id: str, frame: dict[str, Any]) -> list[RpcEvent]:
        """Parse a notification frame and return created records."""
        method = frame.get("method")
        params = frame.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return []
        created: list[RpcEvent] = []
        if method == "NotifyEvent" and isinstance(params.get("events"), list):
            for item in params["events"]:
                if not isinstance(item, dict):
                    continue
                record = RpcEvent(
                    timestamp=float(item.get("ts", params.get("ts", time.time()))),
                    device_id=device_id,
                    component=item.get("component") if isinstance(item.get("component"), str) else None,
                    event=str(item.get("event", "NotifyEvent")),
                    payload=dict(item),
                )
                self._append(record)
                created.append(record)
        else:
            record = RpcEvent(
                timestamp=float(params.get("ts", time.time())),
                device_id=device_id,
                component=None,
                event=method,
                payload=dict(params),
            )
            self._append(record)
            created.append(record)
        return created

    def _append(self, event: RpcEvent) -> None:
        self._events.append(event)
        for listener in tuple(self._listeners):
            listener(event)

    def list(
        self,
        *,
        device_id: str | None = None,
        event_filter: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return newest matching events."""
        values = reversed(self._events)
        result: list[dict[str, Any]] = []
        for event in values:
            if device_id is not None and event.device_id != device_id:
                continue
            if event_filter and event_filter.lower() not in event.event.lower():
                continue
            result.append(event.as_dict())
            if len(result) >= limit:
                break
        return result

    def subscribe(self, listener: Callable[[RpcEvent], None]) -> Callable[[], None]:
        """Subscribe to new records."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

