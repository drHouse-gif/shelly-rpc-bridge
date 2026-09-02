"""Capability discovery for present and future Shelly Gen2+ devices."""

from __future__ import annotations

import time
from typing import Any

from .models import CapabilitySet
from .rpc import RpcError, RpcProtocolError, RpcTransport

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
    components = await async_get_all_components(transport)
    methods: dict[str, Any] | None = None
    try:
        methods = await transport.async_call("Shelly.ListMethods")
        if not isinstance(methods, dict):
            raise RpcProtocolError("Shelly.ListMethods returned an invalid response")
    except RpcError:
        pass
    return parse_capabilities(components, methods)


async def async_get_all_components(
    transport: RpcTransport, *, include: tuple[str, ...] = ("config", "status")
) -> dict[str, Any]:
    """Read every GetComponents page with a defensive upper bound."""
    components: list[dict[str, Any]] = []
    offset = 0
    cfg_rev: int | None = None
    total: int | None = None
    for _ in range(100):
        page = await transport.async_call(
            "Shelly.GetComponents", {"include": list(include), "offset": offset}
        )
        if not isinstance(page, dict):
            raise RpcProtocolError("Shelly.GetComponents returned an invalid response")
        raw = page.get("components", [])
        if not isinstance(raw, list):
            raise RpcProtocolError("Shelly.GetComponents returned an invalid component list")
        components.extend(item for item in raw if isinstance(item, dict))
        if isinstance(page.get("cfg_rev"), int):
            cfg_rev = page["cfg_rev"]
        if isinstance(page.get("total"), int):
            total = page["total"]
        if not raw or total is None or len(components) >= total:
            break
        offset += len(raw)
    else:
        raise RpcProtocolError("Shelly.GetComponents exceeded the pagination limit")
    return {
        "components": components,
        "offset": 0,
        "total": total if total is not None else len(components),
        "cfg_rev": cfg_rev,
    }
