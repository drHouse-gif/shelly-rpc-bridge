"""Controllable fake Shelly Gen2+ HTTP and WebSocket RPC server."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

from aiohttp import WSMsgType, web


class FakeShellyRpcServer:
    """Small real-socket test harness for transport and reconnect tests."""

    def __init__(self) -> None:
        self.app = web.Application()
        self.app.router.add_post("/rpc", self._http_rpc)
        self.app.router.add_get("/rpc", self._websocket_rpc)
        self.runner = web.AppRunner(self.app)
        self.site: web.TCPSite | None = None
        self.host = "127.0.0.1"
        self.port = 0
        self.password = "test-secret"
        self.require_http_auth = False
        self.require_ws_auth = False
        self.disconnect_once = False
        self._did_disconnect = False
        self.requests: list[dict[str, Any]] = []
        self.methods = [
            "Shelly.GetDeviceInfo",
            "Shelly.GetStatus",
            "Shelly.GetConfig",
            "Shelly.GetComponents",
            "Shelly.ListMethods",
            "Switch.SetConfig",
            "Script.List",
            "Script.GetCode",
            "Script.PutCode",
        ]

    async def start(self) -> "FakeShellyRpcServer":
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, 0)
        await self.site.start()
        sockets = self.site._server.sockets  # type: ignore[union-attr]
        self.port = int(sockets[0].getsockname()[1])
        return self

    async def close(self) -> None:
        await self.runner.cleanup()

    async def _http_rpc(self, request: web.Request) -> web.Response:
        if self.require_http_auth and not self._valid_http_auth(request):
            return web.Response(
                status=401,
                headers={
                    "WWW-Authenticate": (
                        'Digest realm="shelly", nonce="nonce123", algorithm=SHA-256, qop="auth"'
                    )
                },
            )
        body = await request.text()
        if body == "malformed-request":
            return web.Response(text="not json", content_type="application/json")
        frame = json.loads(body)
        return await self._http_response(frame)

    async def _http_response(self, frame: dict[str, Any]) -> web.Response:
        method = frame.get("method")
        self.requests.append(frame)
        if method == "Test.Timeout":
            await asyncio.sleep(1)
        if method == "Test.Malformed":
            return web.Response(text="{broken", content_type="application/json")
        if method == "Test.Error":
            return web.json_response(
                {"id": frame["id"], "error": {"code": -103, "message": "Unsupported"}}
            )
        if method == "Test.Null":
            return web.json_response({"id": frame["id"], "result": None})
        return web.json_response(
            {"id": frame["id"], "result": self.result(method, frame.get("params"))}
        )

    async def _websocket_rpc(self, request: web.Request) -> web.WebSocketResponse:
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        tasks: set[asyncio.Task[None]] = set()
        async for message in socket:
            if message.type is not WSMsgType.TEXT:
                continue
            frame = json.loads(message.data)
            self.requests.append(frame)
            if self.disconnect_once and not self._did_disconnect:
                self._did_disconnect = True
                await socket.close()
                break
            task = asyncio.create_task(self._ws_response(socket, frame))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return socket

    async def _ws_response(self, socket: web.WebSocketResponse, frame: dict[str, Any]) -> None:
        method = frame.get("method")
        if self.require_ws_auth and not self._valid_ws_auth(frame.get("auth")):
            challenge = json.dumps({"realm": "shelly", "nonce": 123456789})
            await socket.send_json(
                {"id": frame["id"], "error": {"code": 401, "message": challenge}}
            )
            return
        if method == "Test.Timeout":
            return
        if method == "Test.Malformed":
            await socket.send_json({"id": frame["id"], "result": "not-an-object"})
            return
        if method == "Test.Error":
            await socket.send_json(
                {"id": frame["id"], "error": {"code": -103, "message": "Unsupported"}}
            )
            return
        if method == "Test.Null":
            await socket.send_json({"id": frame["id"], "result": None})
            return
        if method == "Test.Delayed":
            await asyncio.sleep(0.02)
        await socket.send_json(
            {"id": frame["id"], "result": self.result(method, frame.get("params"))}
        )

    def result(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        responses: dict[str, dict[str, Any]] = {
            "Shelly.GetDeviceInfo": {
                "id": "shellyplus1pm-test",
                "name": "Test Relay",
                "model": "SNSW-001P16EU",
                "gen": 2,
                "mac": "AABBCCDDEEFF",
                "ver": "1.5.1",
            },
            "Shelly.GetStatus": {
                "sys": {"uptime": 100, "ram_free": 60000, "ram_size": 100000},
                "wifi": {"rssi": -55},
                "switch:0": {"output": False},
            },
            "Shelly.GetConfig": {"sys": {"device": {"name": "Test Relay"}}},
            "Shelly.GetComponents": {
                "components": [
                    {
                        "key": "switch:0",
                        "config": {"id": 0, "name": "Relay"},
                        "status": {"output": False},
                    },
                    {"key": "wifi", "config": {"ssid": "test", "pass": None}},
                ]
            },
            "Shelly.ListMethods": {"methods": self.methods},
            "Script.List": {"scripts": [{"id": 1, "name": "Example", "enable": True}]},
            "Script.GetCode": {"data": "print('ok')", "left": 0},
        }
        return responses.get(method, {"echo": params or {}, "method": method})

    def _valid_http_auth(self, request: web.Request) -> bool:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Digest "):
            return False
        fields = {
            match.group(1): match.group(2).strip('"')
            for match in re.finditer(r"(\w+)=((?:\"[^\"]*\")|[^,]+)", header[7:])
        }
        required = {"username", "realm", "nonce", "uri", "response", "nc", "cnonce"}
        if not required.issubset(fields) or fields["username"] != "admin":
            return False
        ha1 = hashlib.sha256(f"admin:shelly:{self.password}".encode()).hexdigest()
        ha2 = hashlib.sha256(f"POST:{fields['uri']}".encode()).hexdigest()
        expected = hashlib.sha256(
            f"{ha1}:nonce123:{fields['nc']}:{fields['cnonce']}:auth:{ha2}".encode()
        ).hexdigest()
        return fields["response"] == expected

    def _valid_ws_auth(self, auth: Any) -> bool:
        if not isinstance(auth, dict) or auth.get("username") != "admin":
            return False
        ha1 = hashlib.sha256(f"admin:shelly:{self.password}".encode()).hexdigest()
        ha2 = hashlib.sha256(b"dummy_method:dummy_uri").hexdigest()
        expected = hashlib.sha256(
            f"{ha1}:123456789:{auth.get('nc')}:{auth.get('cnonce')}:auth:{ha2}".encode()
        ).hexdigest()
        return auth.get("response") == expected
