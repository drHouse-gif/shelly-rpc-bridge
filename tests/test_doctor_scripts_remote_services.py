"""Diagnostics, scripts, remote auth, and action schema tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.shelly_toolkit.doctor import ShellyDoctor
from custom_components.shelly_toolkit.models import CapabilitySet, ConnectionKind, ToolkitDevice
from custom_components.shelly_toolkit.remote import (
    RemoteServer,
    hash_remote_secret,
    new_remote_credential,
    normalize_credentials,
)
from custom_components.shelly_toolkit.scripts import _utf8_chunks
from custom_components.shelly_toolkit.services import (
    CLONE_SCHEMA,
    RESTART_SCRIPT_SCHEMA,
    RESTORE_SCHEMA,
    RPC_SCHEMA,
)


class DoctorManager:
    def __init__(self, device) -> None:
        self.device = device
        self.hass = SimpleNamespace()

    async def async_refresh_device(self, device_id):
        return self.device

    async def async_call(self, device_id, method, params=None):
        if method == "Script.List":
            return {"scripts": [{"id": 1}]}
        if method == "Script.GetStatus":
            return {"running": True, "errors": []}
        return {}

    def get_device(self, device_id):
        return self.device


async def test_doctor_uses_only_available_evidence(monkeypatch) -> None:
    device = ToolkitDevice(
        id="local:test",
        connection=ConnectionKind.LOCAL,
        name="Hot weak relay",
        online=True,
        info={"model": "SNSW-001P16EU", "ver": "1.5.1"},
        status={
            "wifi": {"rssi": -76},
            "sys": {"temperature": {"tC": 74}, "ram_free": 5, "ram_size": 100},
        },
        capabilities=CapabilitySet(methods={"Script.List"}),
    )
    doctor = ShellyDoctor(DoctorManager(device))
    monkeypatch.setattr(doctor, "_sync_repairs", lambda *args: None)
    result = await doctor.async_run(device.id)
    findings = {item["key"]: item for item in result["findings"]}
    assert findings["wifi"]["severity"] == "WARNING"
    assert findings["temperature"]["severity"] == "WARNING"
    assert findings["ram_free"]["severity"] == "ERROR"
    assert "reboots" not in findings
    assert result["health"] < 100


async def test_doctor_reports_auth_failure_without_inventing_metrics(monkeypatch) -> None:
    device = ToolkitDevice(
        id="local:offline",
        connection=ConnectionKind.LOCAL,
        name="Offline",
        online=False,
        last_error="RpcAuthError",
    )
    doctor = ShellyDoctor(DoctorManager(device))
    monkeypatch.setattr(doctor, "_sync_repairs", lambda *args: None)
    result = await doctor.async_run(device.id)
    assert result["findings"] == [
        {
            "key": "connectivity",
            "severity": "ERROR",
            "title": "Authentication failed",
            "value": None,
            "evidence": "RpcAuthError",
        }
    ]


def test_script_chunks_preserve_multibyte_utf8() -> None:
    code = "😀" * 3000 + "\nprint('done')"
    chunks = _utf8_chunks(code, 4096)
    assert "".join(chunks) == code
    assert all(len(chunk.encode()) <= 4096 for chunk in chunks)


def test_remote_credentials_are_hashed_bound_and_revocable() -> None:
    record, secret = new_remote_credential("Office")
    assert secret not in str(record)
    assert record["secret_hash"] == hash_remote_secret(secret)
    server = RemoteServer()
    server.configure(
        [record],
        bind_callback=lambda *_: None,
        connect_callback=lambda *_: None,
        disconnect_callback=lambda *_: None,
    )
    assert server.authenticate(record["id"], secret)
    assert not server.authenticate(record["id"], "wrong")
    migrated = normalize_credentials(
        [{"id": "legacy", "name": "Legacy", "token": "plaintext-token"}]
    )
    assert "token" not in migrated[0]
    assert migrated[0]["secret_hash"] == hash_remote_secret("plaintext-token")


def test_service_schemas_reject_unsafe_input() -> None:
    data = RPC_SCHEMA({"device_id": "local:test", "method": "Shelly.GetStatus"})
    assert data["params"] == {}
    assert data["confirm"] is False
    with pytest.raises(vol.Invalid):
        RPC_SCHEMA({"device_id": "x", "method": "Shelly.GetStatus"})
    with pytest.raises(vol.Invalid):
        RESTORE_SCHEMA(
            {"backup_id": "one", "target_device_id": "local:test", "confirm": False}
        )
    with pytest.raises(vol.Invalid):
        CLONE_SCHEMA(
            {
                "source_device_id": "local:one",
                "target_device_id": "local:two",
                "mode": "raw",
                "confirm": True,
            }
        )
    with pytest.raises(vol.Invalid):
        RESTART_SCRIPT_SCHEMA({"device_id": "local:test", "script_id": 0})
