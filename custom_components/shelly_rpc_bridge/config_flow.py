"""Config flow for Shelly RPC Bridge."""

from __future__ import annotations

import hashlib
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_TOKEN

from .bridge import (
    BridgeAuthError,
    BridgeProtocolError,
    BridgeUnavailable,
    async_validate_connection,
    normalize_relay_url,
)
from .const import CONF_RELAY_URL, CONF_SITE_TOKEN, DOMAIN


class ShellyRpcBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure a relay connection through the UI."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                relay_url = normalize_relay_url(user_input[CONF_RELAY_URL])
                token = user_input[CONF_TOKEN]
                site_id = await async_validate_connection(self.hass, relay_url, token)
            except ValueError:
                errors["base"] = "invalid_url"
            except BridgeProtocolError:
                errors["base"] = "invalid_protocol"
            except BridgeAuthError:
                errors["base"] = "invalid_auth"
            except BridgeUnavailable:
                errors["base"] = "cannot_connect"
            else:
                unique = hashlib.sha256(
                    f"{relay_url}|{site_id}".encode()
                ).hexdigest()
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Shelly RPC Bridge — {site_id}",
                    data={
                        CONF_RELAY_URL: relay_url,
                        CONF_SITE_TOKEN: token,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_RELAY_URL): str,
                vol.Required(CONF_TOKEN): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
