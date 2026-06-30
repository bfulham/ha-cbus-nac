"""Constants for the C-Bus NAC integration."""

from __future__ import annotations

DOMAIN = "cbus_nac"
NAME = "C-Bus NAC"
VERSION = "0.1.3"

PLATFORMS = ["light", "switch", "binary_sensor"]

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

DEFAULT_PORT = 10001
DEFAULT_INCLUDE_INTERNAL = False
DEFAULT_MOTION_SENSORS = True

PROJECT_STORE_VERSION = 1
PROJECT_STORE_PREFIX = f"{DOMAIN}.project"
EVENT_CBUS = f"{DOMAIN}_event"
