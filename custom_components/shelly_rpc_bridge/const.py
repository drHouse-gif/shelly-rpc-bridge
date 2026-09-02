"""Constants for Shelly RPC Bridge."""

from homeassistant.const import Platform

DOMAIN = "shelly_rpc_bridge"
CONF_RELAY_URL = "relay_url"
CONF_SITE_TOKEN = "site_token"
DEFAULT_RELAY_PATH = "/ha"
PROTOCOL_VERSION = 1

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.COVER,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]
