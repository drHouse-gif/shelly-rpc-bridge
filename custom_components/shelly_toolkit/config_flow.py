"""Config and fallback options flow for Shelly Toolkit."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .const import CONF_LOCAL_DEVICES, CONF_REMOTE_CREDENTIALS, DOMAIN


class ShellyToolkitConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Create one Toolkit hub; targets are added from its panel."""

    VERSION = 1
    MINOR_VERSION = 0

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return fallback options flow."""
        return ShellyToolkitOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm installation and independent-project disclaimer."""
        if self.hass.config_entries.async_entries(DOMAIN):
            return self.async_abort(reason="already_configured")
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Shelly Toolkit",
                data={CONF_LOCAL_DEVICES: [], CONF_REMOTE_CREDENTIALS: []},
            )
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))


class ShellyToolkitOptionsFlow(OptionsFlow):
    """Keep a native path back to the richer admin-only panel."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show informational form."""
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))
