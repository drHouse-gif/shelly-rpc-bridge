"""Config flow for Shelly RPC Bridge."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import CONF_DEVICE_TOKEN, CONF_DEVICE_URL, DOMAIN, WS_PATH


def build_device_url(hass: Any, token: str) -> str:
    """Build the best reachable WebSocket URL for a Shelly device."""
    base_url = get_url(
        hass,
        allow_internal=True,
        allow_external=True,
        allow_cloud=True,
        prefer_external=True,
        prefer_cloud=True,
    )
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit(
        (scheme, parsed.netloc, WS_PATH, urlencode({"token": token}), "")
    )


class ShellyRpcBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Generate a direct Shelly-to-Home-Assistant connection."""

    VERSION = 2
    MINOR_VERSION = 0

    def __init__(self) -> None:
        self._token: str | None = None
        self._device_url: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self.hass.config_entries.async_entries(DOMAIN):
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            self._token = secrets.token_urlsafe(48)
            try:
                self._device_url = build_device_url(self.hass, self._token)
            except NoURLAvailableError:
                self._token = None
                errors["base"] = "no_url"
            else:
                return await self.async_step_generated()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_generated(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._token is None or self._device_url is None:
            return await self.async_step_user()

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Shelly RPC Bridge",
                data={
                    CONF_DEVICE_TOKEN: self._token,
                    CONF_DEVICE_URL: self._device_url,
                },
            )

        return self.async_show_form(
            step_id="generated",
            data_schema=vol.Schema({}),
            description_placeholders={"shelly_url": self._device_url},
        )
