"""Config and token-management flows for Shelly RPC Bridge."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .bridge import BridgeHub, BridgeServer
from .const import (
    CONF_DEVICE_TOKENS,
    CONF_TOKEN_ID,
    CONF_TOKEN_NAME,
    DATA_SERVER,
    DOMAIN,
    WS_PATH,
)
from . import normalized_entry_data, tokens_from_entry


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


def _new_token_record(name: str) -> dict[str, str]:
    return {
        "id": secrets.token_hex(6),
        "name": name.strip() or "Shelly device",
        "token": secrets.token_urlsafe(48),
    }


class ShellyRpcBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Generate the first direct Shelly-to-Home-Assistant connection."""

    VERSION = 3
    MINOR_VERSION = 0

    def __init__(self) -> None:
        self._record: dict[str, str] | None = None
        self._device_url: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return multi-token management flow."""
        return ShellyRpcBridgeOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self.hass.config_entries.async_entries(DOMAIN):
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            self._record = _new_token_record("Primary")
            try:
                self._device_url = build_device_url(self.hass, self._record["token"])
            except NoURLAvailableError:
                self._record = None
                errors["base"] = "no_url"
            else:
                return await self.async_step_generated()

        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({}), errors=errors
        )

    async def async_step_generated(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._record is None or self._device_url is None:
            return await self.async_step_user()
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Shelly RPC Bridge",
                data={CONF_DEVICE_TOKENS: [self._record]},
            )
        return self.async_show_form(
            step_id="generated",
            data_schema=vol.Schema({}),
            description_placeholders={"shelly_url": self._device_url},
        )


class ShellyRpcBridgeOptionsFlow(OptionsFlow):
    """Generate, view and revoke per-device tokens."""

    def __init__(self) -> None:
        self._generated_url: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["generate_token", "view_tokens", "revoke_token"],
        )

    async def _async_store_tokens(self, tokens: list[dict[str, str]]) -> None:
        entry = self.config_entry
        self.hass.config_entries.async_update_entry(
            entry,
            data=normalized_entry_data(entry, tokens),
            version=3,
            minor_version=0,
        )
        server: BridgeServer | None = self.hass.data.get(DOMAIN, {}).get(DATA_SERVER)
        hub = getattr(entry, "runtime_data", None)
        if server is not None and isinstance(hub, BridgeHub):
            await server.async_set_tokens(hub, (item["token"] for item in tokens))

    async def async_step_generate_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            record = _new_token_record(user_input[CONF_TOKEN_NAME])
            try:
                self._generated_url = build_device_url(self.hass, record["token"])
            except NoURLAvailableError:
                errors["base"] = "no_url"
            else:
                tokens = tokens_from_entry(self.config_entry)
                tokens.append(record)
                await self._async_store_tokens(tokens)
                return await self.async_step_token_created()

        return self.async_show_form(
            step_id="generate_token",
            data_schema=vol.Schema(
                {vol.Required(CONF_TOKEN_NAME, default="Shelly device"): str}
            ),
            errors=errors,
        )

    async def async_step_token_created(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._generated_url is None:
            return await self.async_step_init()
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="token_created",
            data_schema=vol.Schema({}),
            description_placeholders={"shelly_url": self._generated_url},
        )

    async def async_step_view_tokens(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        lines: list[str] = []
        for item in tokens_from_entry(self.config_entry):
            try:
                url = build_device_url(self.hass, item["token"])
            except NoURLAvailableError:
                url = "URL unavailable"
            lines.append(f"**{item['name']}**\n\n`{url}`")
        token_list = "\n\n---\n\n".join(lines) if lines else "No tokens configured."
        return self.async_show_form(
            step_id="view_tokens",
            data_schema=vol.Schema({}),
            description_placeholders={"token_list": token_list},
        )

    async def async_step_revoke_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        tokens = tokens_from_entry(self.config_entry)
        choices = {item["id"]: item["name"] for item in tokens}
        if not choices:
            return self.async_abort(reason="no_tokens")

        if user_input is not None:
            selected = user_input[CONF_TOKEN_ID]
            remaining = [item for item in tokens if item["id"] != selected]
            await self._async_store_tokens(remaining)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="revoke_token",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN_ID): vol.In(choices)}),
        )
