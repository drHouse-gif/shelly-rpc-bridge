"""Constants for Shelly Toolkit."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "shelly_toolkit"
NAME: Final = "Shelly Toolkit for Home Assistant"
VERSION: Final = "0.4.0"

CONF_LOCAL_DEVICES: Final = "local_devices"
CONF_REMOTE_CREDENTIALS: Final = "remote_credentials"
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_TRANSPORT: Final = "transport"
CONF_VERIFY_SSL: Final = "verify_ssl"

DATA_REMOTE_SERVER: Final = "remote_server"
DATA_PANEL_REGISTERED: Final = "panel_registered"
DATA_WS_REGISTERED: Final = "websocket_registered"

DEFAULT_PORT: Final = 80
DEFAULT_HTTPS_PORT: Final = 443
DEFAULT_TIMEOUT: Final = 12.0
DEFAULT_SCAN_INTERVAL: Final = 60
MAX_DEVICES: Final = 500
MAX_EVENTS: Final = 500
MAX_BACKUPS: Final = 50
MAX_BACKUP_BYTES: Final = 2_000_000
MAX_RPC_PARAMS_BYTES: Final = 65_536

PANEL_URL: Final = "shelly-toolkit"
STATIC_URL: Final = "/shelly_toolkit_static"
REMOTE_WS_PATH: Final = "/api/shelly_toolkit/remote"
HA_EVENT: Final = "shelly_toolkit_event"

DISCLAIMER: Final = (
    "Independent community project. Not affiliated with or endorsed by Shelly Group."
)

TRANSPORT_HTTP: Final = "http"
TRANSPORT_WEBSOCKET: Final = "websocket"
TRANSPORT_REMOTE: Final = "remote"
TRANSPORT_OFFICIAL: Final = "official"

DESTRUCTIVE_RPC_METHODS: Final = frozenset(
    {
        "Shelly.FactoryReset",
        "Shelly.ResetWiFiConfig",
        "Shelly.SetAuth",
        "Shelly.Update",
        "Sys.SetConfig",
        "WiFi.SetConfig",
        "Eth.SetConfig",
        "WS.SetConfig",
        "Cloud.SetConfig",
        "MQTT.SetConfig",
    }
)

SECRET_KEYS: Final = frozenset(
    {
        "access_token",
        "api_key",
        "auth",
        "client_secret",
        "ha1",
        "key",
        "pass",
        "passphrase",
        "passwd",
        "password",
        "private_key",
        "secret",
        "token",
    }
)
