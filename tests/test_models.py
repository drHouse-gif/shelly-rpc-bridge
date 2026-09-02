"""Tests for protocol-independent remote-device state handling."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODELS_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shelly_rpc_bridge"
    / "models.py"
)
SPEC = importlib.util.spec_from_file_location("bridge_models_for_test", MODELS_PATH)
assert SPEC is not None and SPEC.loader is not None
MODELS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODELS
SPEC.loader.exec_module(MODELS)

RemoteDevice = MODELS.RemoteDevice
flatten_scalars = MODELS.flatten_scalars
value_at_path = MODELS.value_at_path


class RemoteDeviceTests(unittest.TestCase):
    def test_snapshot_and_push_notification(self) -> None:
        device = RemoteDevice("shellyproem-test")
        device.apply_snapshot(
            online=True,
            last_seen=123.0,
            info={"model": "SPEM-003CEBEU"},
            components=[
                {
                    "key": "em1:0",
                    "config": {"name": "Grid"},
                    "status": {"voltage": 230.0, "act_power": 100.0},
                }
            ],
        )
        changed = device.apply_rpc_frame(
            {
                "method": "NotifyStatus",
                "params": {"ts": 124.0, "em1:0": {"act_power": 125.5}},
            }
        )
        self.assertTrue(changed)
        self.assertEqual(device.components["em1:0"].status["voltage"], 230.0)
        self.assertEqual(device.components["em1:0"].status["act_power"], 125.5)

    def test_battery_device_remains_available_while_sleeping(self) -> None:
        device = RemoteDevice("shellyht-test")
        device.apply_snapshot(
            online=False,
            last_seen=123.0,
            info={},
            components=[
                {
                    "key": "devicepower:0",
                    "status": {"battery": {"percent": 91}},
                }
            ],
        )
        self.assertTrue(device.sleeping)
        self.assertTrue(device.available)

    def test_nested_measurements_are_flattened_and_readable(self) -> None:
        status = {
            "temperature": {"tC": 24.5},
            "aenergy": {"total": 55.2, "by_minute": [1, 2, 3]},
        }
        flattened = dict(flatten_scalars(status))
        self.assertEqual(flattened[("temperature", "tC")], 24.5)
        self.assertEqual(flattened[("aenergy", "total")], 55.2)
        self.assertNotIn(("aenergy", "by_minute"), flattened)
        self.assertEqual(value_at_path(status, ("temperature", "tC")), 24.5)


if __name__ == "__main__":
    unittest.main()
