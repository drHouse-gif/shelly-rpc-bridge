"""Shared Home Assistant custom-integration test fixtures."""

from __future__ import annotations

import pytest

from .fake_shelly import FakeShellyRpcServer


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom_components in Home Assistant tests."""
    yield


@pytest.fixture
async def fake_shelly(socket_enabled) -> FakeShellyRpcServer:
    """Run a fake Shelly RPC server on a random local port."""
    server = await FakeShellyRpcServer().start()
    try:
        yield server
    finally:
        await server.close()
