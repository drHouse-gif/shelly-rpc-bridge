"""Capability parsing and bounded event history tests."""

from __future__ import annotations

from custom_components.shelly_toolkit.capabilities import parse_capabilities
from custom_components.shelly_toolkit.events import EventStore


def test_capability_detection_uses_components_and_discovered_methods() -> None:
    capabilities = parse_capabilities(
        {
            "components": [
                {"key": "switch:0", "config": {}},
                {"key": "input:0", "config": {}},
                {"key": "modbus", "config": {}},
            ]
        },
        {"methods": ["Modbus.SetConfig", "FutureComponent.DoThing", 4]},
    )
    assert {"switch", "input", "modbus", "futurecomponent"} <= capabilities.namespaces
    assert "Switch.Set" in capabilities.methods
    assert "Modbus.SetConfig" in capabilities.methods
    assert capabilities.components["input:0"]["config"] == {}


def test_event_store_is_bounded_and_filterable() -> None:
    store = EventStore(maxlen=2)
    observed = []
    unsubscribe = store.subscribe(observed.append)
    store.add_frame(
        "remote:one",
        {
            "method": "NotifyEvent",
            "params": {
                "events": [
                    {"ts": 1, "component": "input:0", "event": "single_push"},
                    {"ts": 2, "component": "switch:0", "event": "toggle"},
                ]
            },
        },
    )
    store.add_frame("remote:two", {"method": "NotifyStatus", "params": {"ts": 3}})
    unsubscribe()
    assert len(observed) == 3
    assert [item["event"] for item in store.list(limit=10)] == ["NotifyStatus", "toggle"]
    assert store.list(device_id="remote:one", event_filter="toggle")[0]["component"] == "switch:0"
