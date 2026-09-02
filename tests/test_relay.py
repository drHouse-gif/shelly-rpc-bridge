"""End-to-end protocol tests using simulated Shelly and HA peers."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "relay"))

from bridge_relay.server import BridgeRelay, SiteCredentials  # noqa: E402


async def receive_until(websocket, kind: str) -> dict:
    """Receive bridge envelopes until the requested kind arrives."""
    async with asyncio.timeout(3):
        while True:
            value = json.loads(await websocket.recv())
            if value.get("bridge") == kind:
                return value


class RelayProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.relay = BridgeRelay(
            [
                SiteCredentials(
                    site_id="test-home",
                    device_token="device-token-that-is-definitely-long-enough",
                    ha_token="home-assistant-token-that-is-long-enough",
                )
            ]
        )
        self.server = await serve(
            self.relay.handle_connection,
            "127.0.0.1",
            0,
            process_request=self.relay.process_request,
            ping_interval=None,
        )
        self.port = self.server.sockets[0].getsockname()[1]
        self.connections = []

    async def asyncTearDown(self) -> None:
        for websocket in self.connections:
            await websocket.close()
        self.server.close()
        await self.server.wait_closed()

    async def open(self, path: str):
        websocket = await connect(f"ws://127.0.0.1:{self.port}{path}")
        self.connections.append(websocket)
        return websocket

    async def identify_device(self, device_id: str = "shellyproem-test123"):
        ha = await self.open(
            "/ha?token=home-assistant-token-that-is-long-enough"
        )
        hello = json.loads(await ha.recv())
        self.assertEqual(hello["bridge"], "hello")
        self.assertEqual(hello["site_id"], "test-home")

        device = await self.open(
            "/device?token=device-token-that-is-definitely-long-enough"
        )
        identify = json.loads(await device.recv())
        self.assertEqual(identify["method"], "Shelly.GetDeviceInfo")
        await device.send(
            json.dumps(
                {
                    "id": identify["id"],
                    "src": device_id,
                    "dst": identify["src"],
                    "result": {
                        "id": device_id,
                        "model": "SPEM-003CEBEU",
                        "gen": 2,
                    },
                }
            )
        )
        online = await receive_until(ha, "device_online")
        self.assertEqual(online["device_id"], device_id)

        components_request = json.loads(await device.recv())
        self.assertEqual(components_request["method"], "Shelly.GetComponents")
        await device.send(
            json.dumps(
                {
                    "id": components_request["id"],
                    "src": device_id,
                    "dst": components_request["src"],
                    "result": {
                        "components": [
                            {
                                "key": "em1:0",
                                "config": {"name": "Main meter"},
                                "status": {"voltage": 230.4, "act_power": 421.2},
                            }
                        ]
                    },
                }
            )
        )
        snapshot = await receive_until(ha, "device_snapshot")
        self.assertEqual(snapshot["components"][0]["key"], "em1:0")
        return ha, device, device_id

    async def test_rpc_is_routed_in_both_directions(self) -> None:
        ha, device, device_id = await self.identify_device()
        frame = {
            "id": 55,
            "src": "ha_test",
            "method": "Shelly.GetStatus",
        }
        await ha.send(
            json.dumps({"bridge": "rpc", "device_id": device_id, "frame": frame})
        )
        request = json.loads(await device.recv())
        self.assertEqual(request, frame)

        response = {
            "id": 55,
            "src": device_id,
            "dst": "ha_test",
            "result": {"em1:0": {"act_power": 422.0}},
        }
        await device.send(json.dumps(response))
        envelope = await receive_until(ha, "device_message")
        while envelope.get("frame", {}).get("id") != 55:
            envelope = await receive_until(ha, "device_message")
        self.assertEqual(envelope["frame"], response)

    async def test_dangerous_rpc_is_blocked(self) -> None:
        ha, _device, device_id = await self.identify_device()
        await ha.send(
            json.dumps(
                {
                    "bridge": "rpc",
                    "device_id": device_id,
                    "frame": {
                        "id": 77,
                        "src": "ha_test",
                        "method": "Shelly.FactoryReset",
                    },
                }
            )
        )
        error = await receive_until(ha, "error")
        self.assertEqual(error["code"], "rpc_method_blocked")

    async def test_invalid_token_is_rejected(self) -> None:
        websocket = await self.open("/ha?token=wrong")
        await websocket.wait_closed()
        self.assertEqual(websocket.close_code, 4003)


if __name__ == "__main__":
    unittest.main()
