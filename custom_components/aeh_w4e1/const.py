"""Constants for the AEH-W4E1 integration."""

DOMAIN = "aeh_w4e1"
MANUFACTURER = "Hisense"
DEFAULT_NAME = "Air Conditioner"
DEFAULT_MODEL = "AEH-W4E1"

# Configuration entry data keys.
CONF_LANIP_KEY = "lanip_key"
CONF_LANIP_KEY_ID = "lanip_key_id"
CONF_HOST = "host"
CONF_DEVICE_PORT = "device_port"
CONF_TEMP_UNIT = "temp_unit"
CONF_DSN = "dsn"
CONF_MAC = "mac"
CONF_MODEL = "model"
CONF_SW_VERSION = "sw_version"
CONF_SETUP_METHOD = "setup_method"
CONF_APP = "app"
CONF_CLOUD_USER = "cloud_user"
CONF_CLOUD_PASSWORD = "cloud_password"
CONF_CLOUD_DEVICE = "cloud_device"

# Options entry keys.
CONF_SERVER_PORT = "server_port"  # 0 = OS-assigned ephemeral port.
CONF_LOCAL_IP = "local_ip"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_KEEPALIVE_INTERVAL = "keepalive_interval"
CONF_SCAN_NETWORK = "scan_network"  # Optional CIDR for targeted scans (rediscovery/service).

DEFAULT_DEVICE_PORT = 80
DEFAULT_SERVER_PORT = 0  # Let the OS pick a free port; no conflicts by default.
DEFAULT_LOCAL_IP = ""  # Empty = auto-detect.
DEFAULT_REFRESH_INTERVAL = 600.0
DEFAULT_KEEPALIVE_INTERVAL = 10.0
MIN_REFRESH_INTERVAL = 60.0
MIN_KEEPALIVE_INTERVAL = 5.0

SETUP_METHOD_MANUAL = "manual"
SETUP_METHOD_CLOUD = "cloud"

# Temperature limits.
TEMP_MIN_C = 16
TEMP_MAX_C = 30
TEMP_MIN_F = 61
TEMP_MAX_F = 86

# Signals fired by the runtime (payload: property name, value).
SIGNAL_UPDATE = "{domain}_update_{entry_id}"
SIGNAL_AVAILABLE = "{domain}_available_{entry_id}"

# Services.
SERVICE_SEND_COMMAND = "send_command"
SERVICE_REQUEST_STATUS_REFRESH = "request_status_refresh"
SERVICE_SCAN_NETWORK = "scan_network"

# Repair issue ids.
ISSUE_UNKNOWN_KEY_ID = "unknown_key_id"
ISSUE_PORT_BIND_FAILED = "port_bind_failed"

# Ayla LAN mode fixed values.
LOCAL_REG_URI = "/local_lan"
KEY_EXCHANGE_PATH = "/local_lan/key_exchange.json"
COMMANDS_PATH = "/local_lan/commands.json"
DATAPONT_PATHS = (
    "/local_lan/property/datapoint.json",
    "/local_lan/property/datapoint/ack.json",
    "/local_lan/node/property/datapoint.json",
    "/local_lan/node/property/datapoint/ack.json",
)
