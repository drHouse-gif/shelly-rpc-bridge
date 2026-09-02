"""Transport behavior against the real-socket fake Shelly server."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from custom_components.shelly_toolkit.rpc import (
    HttpRpcTransport,
    RpcAuthError,
    RpcProtocolError,
    RpcResponseError,
    RpcTimeoutError,
    WebSocketRpcTransport,
)


@pytest.mark.parametrize("transport_class", [HttpRpcTransport, WebSocketRpcTransport])
async def test_normal_and_concurrent_requests(fake_shelly, transport_class) -> None:
    async with aiohttp.ClientSession() as session:
        transport = transport_class(session, fake_shelly.host, port=fake_shelly.port)
        info, echoed = await asyncio.gather(
            transport.async_call("Shelly.GetDeviceInfo"),
            transport.async_call("Test.Delayed", {"number": 2}),
        )
        assert info["gen"] == 2
        assert echoed == {"echo": {"number": 2}, "method": "Test.Delayed"}
        assert await transport.async_call("Test.Null") is None
        assert transport.connected
        await transport.async_close()


@pytest.mark.parametrize("transport_class", [HttpRpcTransport, WebSocketRpcTransport])
async def test_rpc_error(fake_shelly, transport_class) -> None:
    async with aiohttp.ClientSession() as session:
        transport = transport_class(session, fake_shelly.host, port=fake_shelly.port)
        with pytest.raises(RpcResponseError) as raised:
            await transport.async_call("Test.Error")
        assert raised.value.code == -103
        await transport.async_close()


async def test_http_timeout_and_malformed_response(fake_shelly) -> None:
    async with aiohttp.ClientSession() as session:
        transport = HttpRpcTransport(session, fake_shelly.host, port=fake_shelly.port, timeout=0.03)
        with pytest.raises(RpcTimeoutError):
            await transport.async_call("Test.Timeout")
        with pytest.raises(RpcProtocolError):
            await transport.async_call("Test.Malformed")


async def test_websocket_timeout_and_malformed_response(fake_shelly) -> None:
    async with aiohttp.ClientSession() as session:
        transport = WebSocketRpcTransport(
            session, fake_shelly.host, port=fake_shelly.port, timeout=0.03
        )
        with pytest.raises(RpcTimeoutError):
            await transport.async_call("Test.Timeout")
        with pytest.raises(RpcProtocolError):
            await transport.async_call("Test.Malformed")
        await transport.async_close()


async def test_websocket_disconnect_and_reconnect(fake_shelly) -> None:
    fake_shelly.disconnect_once = True
    async with aiohttp.ClientSession() as session:
        transport = WebSocketRpcTransport(
            session, fake_shelly.host, port=fake_shelly.port, timeout=0.2
        )
        result = await transport.async_call("Shelly.GetDeviceInfo")
        assert result["id"] == "shellyplus1pm-test"
        assert fake_shelly._did_disconnect
        await transport.async_close()


async def test_http_digest_authentication(fake_shelly) -> None:
    fake_shelly.require_http_auth = True
    async with aiohttp.ClientSession() as session:
        good = HttpRpcTransport(
            session,
            fake_shelly.host,
            port=fake_shelly.port,
            password=fake_shelly.password,
        )
        assert (await good.async_call("Shelly.GetDeviceInfo"))["gen"] == 2
        bad = HttpRpcTransport(session, fake_shelly.host, port=fake_shelly.port, password="wrong")
        with pytest.raises(RpcAuthError):
            await bad.async_call("Shelly.GetDeviceInfo")


async def test_websocket_digest_authentication(fake_shelly) -> None:
    fake_shelly.require_ws_auth = True
    async with aiohttp.ClientSession() as session:
        good = WebSocketRpcTransport(
            session,
            fake_shelly.host,
            port=fake_shelly.port,
            password=fake_shelly.password,
        )
        assert (await good.async_call("Shelly.GetDeviceInfo"))["gen"] == 2
        await good.async_close()
        bad = WebSocketRpcTransport(
            session, fake_shelly.host, port=fake_shelly.port, password="wrong"
        )
        with pytest.raises(RpcAuthError):
            await bad.async_call("Shelly.GetDeviceInfo")
        await bad.async_close()
