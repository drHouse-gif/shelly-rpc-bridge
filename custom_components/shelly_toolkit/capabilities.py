"""Capability discovery for present and future Shelly Gen2+ devices."""

from __future__ import annotations

import time
from typing import Any

from .models import CapabilitySet
from .rpc import RpcError, RpcTransport

READ_METHODS_BY_COMPONENT = {
    "switch": {"Switch.GetConfig", "Switch.GetStatus", "Switch.Set"},
    "input": {"Input.GetConfig", "Input.GetStatus"},
    "cover": {"Cover.GetConfig", "Cover.GetStatus", "Cover.SetConfig"},
    "light": {"Light.GetConfig", "Light.GetStatus", "Light.Set"},
    "rgb": {"RGB.GetConfig", "RGB.GetStatus", "RGB.Set"},
    "rgbw": {"RGBW.GetConfig", "RGBW.GetStatus", "RGBW.Set"},
    "script": {
        "Script.List",
        "Script.GetCode",
        "Script.GetStatus",
        "Script.PutCode",
        "Script.Start",
        "Script.Stop",
    },
    "schedule": {"Schedule.List", "Schedule.Create", "Schedule.Update"},
    "webhook": {"Webhook.List", "Webhook.Create", "Webhook.Update"},
}


def parse_capabilities(
    components_result: dict[str, Any], methods_result: dict[str, Any] | None = None
) -> CapabilitySet:
    """Parse GetComponents/ListMethods without a model whitelist."""
    capabilities = CapabilitySet(discovered_at=time.time())
    raw_components = components_result.get("components", [])
    if isinstance(raw_components, list):
        for raw in raw_components:
            if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
                continue
            key = raw["key"]
            capabilities.components[key] = raw
            namespace = key.split(":", 1)[0].lower()
            capabilities.namespaces.add(namespace)
            capabilities.methods.update(READ_METHODS_BY_COMPONENT.get(namespace, set()))
    if methods_result is not None:
        raw_methods = methods_result.get("methods", [])
        if isinstance(raw_methods, list):
            capabilities.methods.update(
                method for method in raw_methods if isinstance(method, str) and "." in method
            )
    capabilities.methods.update(
        {
            "Shelly.GetDeviceInfo",
            "Shelly.GetStatus",
            "Shelly.GetConfig",
            "Shelly.GetComponents",
            "Shelly.ListMethods",
        }
    )
    capabilities.namespaces.update(
        method.split(".", 1)[0].lower() for method in capabilities.methods
    )
    return capabilities


async def async_discover_capabilities(transport: RpcTransport) -> CapabilitySet:
    """Discover components and methods, tolerating older firmware."""
    components = await transport.async_call(
        "Shelly.GetComponents", {"include": ["config", "status"]}
    )
    methods: dict[str, Any] | None = None
    try:
        methods = await transport.async_call("Shelly.ListMethods")
    except RpcError:
        pass
    return parse_capabilities(components, methods)

