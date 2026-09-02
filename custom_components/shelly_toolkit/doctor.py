"""Evidence-based Shelly Doctor diagnostics engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .device_manager import DeviceManager
from .models import _temperatures
from .rpc import RpcError


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(slots=True)
class Finding:
    key: str
    severity: Severity
    title: str
    value: Any = None
    evidence: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["severity"] = self.severity.value
        return value


class ShellyDoctor:
    """Diagnose only fields actually provided by the target."""

    def __init__(self, manager: DeviceManager) -> None:
        self.manager = manager
        self._active_issues: dict[str, set[str]] = {}
        self._results: dict[str, dict[str, Any]] = {}

    async def async_run(self, device_id: str) -> dict[str, Any]:
        device = await self.manager.async_refresh_device(device_id)
        findings: list[Finding] = []
        if not device.online:
            severity = Severity.ERROR
            title = "Authentication failed" if device.last_error == "RpcAuthError" else "Device is offline"
            findings.append(
                Finding("connectivity", severity, title, evidence=device.last_error)
            )
            self._sync_repairs(device_id, findings)
            result = self._result(device, findings)
            self._results[device_id] = result
            return result
        findings.append(Finding("connectivity", Severity.INFO, "Connectivity OK"))
        findings.append(Finding("rpc", Severity.INFO, "RPC OK"))
        recent_failures = device.rpc_metrics.get("recent_failures", [])
        if isinstance(recent_failures, list) and len(recent_failures) >= 3:
            findings.append(
                Finding(
                    "rpc_stability",
                    Severity.WARNING,
                    "Unstable RPC connection",
                    len(recent_failures),
                    "RPC failures during the last 15 minutes",
                )
            )

        wifi = device.status.get("wifi")
        if isinstance(wifi, dict) and isinstance(wifi.get("rssi"), (int, float)):
            rssi = float(wifi["rssi"])
            severity = Severity.ERROR if rssi <= -85 else Severity.WARNING if rssi <= -70 else Severity.INFO
            findings.append(Finding("wifi", severity, "Wi-Fi signal", rssi, "wifi.rssi"))

        for index, value in enumerate(_temperatures(device.status)):
            severity = Severity.ERROR if value >= 85 else Severity.WARNING if value >= 70 else Severity.INFO
            findings.append(
                Finding(
                    f"temperature_{index}",
                    severity,
                    "Device temperature",
                    value,
                    "component status temperature.tC",
                )
            )

        sys_status = device.status.get("sys")
        if isinstance(sys_status, dict):
            for free_key, total_key, label in (
                ("ram_free", "ram_size", "Free memory"),
                ("fs_free", "fs_size", "Free filesystem"),
            ):
                free, total = sys_status.get(free_key), sys_status.get(total_key)
                if isinstance(free, (int, float)) and isinstance(total, (int, float)) and total > 0:
                    percent = round(float(free) / float(total) * 100, 1)
                    severity = Severity.ERROR if percent < 10 else Severity.WARNING if percent < 20 else Severity.INFO
                    findings.append(
                        Finding(free_key, severity, label, percent, f"sys.{free_key}/{total_key}")
                    )
            if sys_status.get("restart_required") is True:
                findings.append(
                    Finding(
                        "restart_required",
                        Severity.WARNING,
                        "Device reports restart required",
                        True,
                        "sys.restart_required",
                    )
                )

        if device.firmware:
            findings.append(
                Finding(
                    "firmware",
                    Severity.INFO,
                    "Firmware information available",
                    device.firmware,
                    "Shelly.GetDeviceInfo",
                )
            )

        component_errors = _component_error_findings(device.status)
        findings.extend(component_errors)
        if "Script.List" in device.capabilities.methods:
            findings.extend(await self._script_findings(device_id))
        result = self._result(device, findings)
        self._results[device_id] = result
        self._sync_repairs(device_id, findings)
        return result

    def latest(self) -> list[dict[str, Any]]:
        """Return the latest cached report for each explicitly diagnosed device."""
        return list(self._results.values())

    async def _script_findings(self, device_id: str) -> list[Finding]:
        findings: list[Finding] = []
        try:
            result = await self.manager.async_call(device_id, "Script.List")
        except RpcError as err:
            return [Finding("scripts", Severity.WARNING, "Could not inspect scripts", evidence=type(err).__name__)]
        if not isinstance(result, dict):
            return [
                Finding(
                    "scripts",
                    Severity.WARNING,
                    "Could not inspect scripts",
                    evidence="invalid Script.List response",
                )
            ]
        scripts = result.get("scripts", [])
        if not isinstance(scripts, list):
            return findings
        for item in scripts:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                continue
            try:
                status = await self.manager.async_call(
                    device_id, "Script.GetStatus", {"id": item["id"]}
                )
            except RpcError as err:
                findings.append(
                    Finding(
                        f"script_{item['id']}",
                        Severity.WARNING,
                        f"Script {item['id']} status unavailable",
                        evidence=type(err).__name__,
                    )
                )
                continue
            if not isinstance(status, dict):
                findings.append(
                    Finding(
                        f"script_{item['id']}",
                        Severity.WARNING,
                        f"Script {item['id']} status unavailable",
                        evidence="invalid Script.GetStatus response",
                    )
                )
                continue
            errors = status.get("errors")
            if errors:
                findings.append(
                    Finding(
                        f"script_{item['id']}",
                        Severity.ERROR,
                        f"Script {item['id']} reports errors",
                        errors,
                        "Script.GetStatus.errors",
                    )
                )
        if not any(item.key.startswith("script_") for item in findings):
            findings.append(Finding("scripts", Severity.INFO, "Scripts OK"))
        return findings

    def _result(self, device: Any, findings: list[Finding]) -> dict[str, Any]:
        penalty = sum(
            25 if finding.severity is Severity.ERROR else 8 if finding.severity is Severity.WARNING else 0
            for finding in findings
        )
        return {
            "device_id": device.id,
            "name": device.name,
            "model": device.model,
            "health": max(0, 100 - penalty),
            "findings": [finding.as_dict() for finding in findings],
        }

    def _sync_repairs(self, device_id: str, findings: list[Finding]) -> None:
        current: set[str] = set()
        for finding in findings:
            issue_id = f"doctor_{device_id}_{finding.key}"
            if finding.severity is Severity.ERROR:
                current.add(issue_id)
                ir.async_create_issue(
                    self.manager.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    is_persistent=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="doctor_issue",
                    translation_placeholders={
                        "device": self.manager.get_device(device_id).name,
                        "problem": finding.title,
                    },
                )
            else:
                ir.async_delete_issue(self.manager.hass, DOMAIN, issue_id)
        for stale_issue in self._active_issues.get(device_id, set()) - current:
            ir.async_delete_issue(self.manager.hass, DOMAIN, stale_issue)
        self._active_issues[device_id] = current


def _component_error_findings(status: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for key, value in status.items():
        if not isinstance(value, dict):
            continue
        errors = value.get("errors") or value.get("error")
        if errors:
            findings.append(
                Finding(
                    f"component_{key}",
                    Severity.ERROR,
                    f"{key} reports errors",
                    errors,
                    f"{key}.errors",
                )
            )
    return findings
