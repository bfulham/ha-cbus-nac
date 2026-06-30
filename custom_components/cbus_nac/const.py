"""Constants for the C-Bus NAC integration."""

from __future__ import annotations

DOMAIN = "cbus_nac"
NAME = "C-Bus NAC"
VERSION = "0.1.4"

PLATFORMS = ["light", "switch", "binary_sensor", "sensor"]

CONF_PROJECT_KEY = "project_key"
CONF_PROJECT_HASH = "project_hash"
CONF_PROJECT_ID = "project_id"
CONF_PROJECT_NAME = "project_name"
CONF_PROJECT_FILE = "project_file"
CONF_NETWORK = "network"
CONF_ENABLED = "enabled"
CONF_HOST_OVERRIDE = "host_override"
CONF_PORT_OVERRIDE = "port_override"
CONF_MONITOR_APPLICATION = "monitor_application"
CONF_INCLUDE_INTERNAL = "include_internal_groups"
CONF_MOTION_SENSORS = "motion_groups_as_binary_sensors"

CONF_ILLUMINANCE_ENABLED = "illuminance_enabled"
CONF_ILLUMINANCE_POLL_INTERVAL = "illuminance_poll_interval"
CONF_REMOTE_API_SCHEME = "remote_api_scheme"
CONF_REMOTE_API_PORT = "remote_api_port"
CONF_REMOTE_API_USERNAME = "remote_api_username"
CONF_REMOTE_API_PASSWORD = "remote_api_password"
CONF_REMOTE_API_VERIFY_SSL = "remote_api_verify_ssl"

DEFAULT_PORT = 10001
DEFAULT_INCLUDE_INTERNAL = False
DEFAULT_MOTION_SENSORS = True
DEFAULT_ILLUMINANCE_ENABLED = False
DEFAULT_ILLUMINANCE_POLL_INTERVAL = 60
DEFAULT_REMOTE_API_SCHEME = "http"
DEFAULT_REMOTE_API_PORT = 80
DEFAULT_REMOTE_API_USERNAME = "remote"
DEFAULT_REMOTE_API_VERIFY_SSL = False

PROJECT_STORE_VERSION = 1
PROJECT_STORE_PREFIX = f"{DOMAIN}.project"
EVENT_CBUS = f"{DOMAIN}_event"
