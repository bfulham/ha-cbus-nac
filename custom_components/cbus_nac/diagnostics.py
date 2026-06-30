"""Diagnostics for C-Bus NAC."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import DOMAIN
from .runtime import CbusRuntime

TO_REDACT = {"host", "address"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return non-sensitive project and connection diagnostics."""
    runtime: CbusRuntime = hass.data[DOMAIN][entry.entry_id]
    networks = []
    for network in runtime.project["networks"]:
        enabled, host, port, app = runtime.effective_connection(network)
        connection = runtime.connections.get(network["address"])
        networks.append(
            {
                "network": network["address"],
                "name": network["name"],
                "enabled": enabled,
                "host": host,
                "port": port,
                "monitor_application": app,
                "connected": runtime.available(network["address"]),
                "last_error": connection.last_error if connection else None,
                "active_applications": network["active_applications"],
            }
        )
    return async_redact_data(
        {
            "entry": dict(entry.data),
            "project": {
                "name": runtime.project["project_name"],
                "id": runtime.project["project_id"],
                "db_version": runtime.project.get("db_version"),
                "network_count": len(runtime.project["networks"]),
            },
            "networks": networks,
        },
        TO_REDACT,
    )
