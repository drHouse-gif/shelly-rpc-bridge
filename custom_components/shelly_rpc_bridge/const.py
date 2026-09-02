"""Constants for Shelly RPC Bridge."""

from homeassistant.const import Platform

DOMAIN = "shelly_rpc_bridge"
CONF_DEVICE_TOKEN = "device_token"  # legacy 0.2.x
CONF_DEVICE_URL = "device_url"  # legacy 0.2.x
CONF_DEVICE_TOKENS = "device_tokens"
CONF_TOKEN_ID = "token_id"
CONF_TOKEN_NAME = "token_name"
DATA_SERVER = "server"
WS_PATH = "/api/shelly_rpc_bridge"
MAX_DEVICES = 500

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.COVER,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]
