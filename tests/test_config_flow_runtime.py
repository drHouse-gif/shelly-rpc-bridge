"""Config flow and config-entry lifecycle tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shelly_toolkit.const import (
    CONF_LOCAL_DEVICES,
    CONF_REMOTE_CREDENTIALS,
    DOMAIN,
)


async def test_config_flow_creates_single_hub(hass) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    with patch(
        "custom_components.shelly_toolkit.async_setup_entry",
        new=AsyncMock(return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Shelly Toolkit"
    assert result["data"] == {
        CONF_LOCAL_DEVICES: [],
        CONF_REMOTE_CREDENTIALS: [],
    }


async def test_config_flow_aborts_when_already_configured(hass) -> None:
    MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_setup_reload_and_unload_empty_runtime(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Shelly Toolkit",
        unique_id=DOMAIN,
        data={CONF_LOCAL_DEVICES: [], CONF_REMOTE_CREDENTIALS: []},
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.shelly_toolkit.BackupRepository.async_load",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.shelly_toolkit.DeviceManager.async_start",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.shelly_toolkit.DeviceManager.async_close",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.shelly_toolkit.ToolkitCoordinator.async_config_entry_first_refresh",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.shelly_toolkit.ToolkitCoordinator.async_shutdown",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.shelly_toolkit._async_register_panel",
            new=AsyncMock(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert entry.state is ConfigEntryState.NOT_LOADED
