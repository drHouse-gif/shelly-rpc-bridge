"""Constants for Shelly RPC Bridge."""

from homeassistant.const import Platform

DOMAIN = "shelly_rpc_bridge"
CONF_DEVICE_TOKEN = "device_token"
CONF_DEVICE_URL = "device_url"
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
