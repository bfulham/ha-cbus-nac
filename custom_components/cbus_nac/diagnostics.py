"""Diagnostics for C-Bus NAC."""

from __future__ import annotations

from collections import Counter

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_REMOTE_API_PASSWORD, DOMAIN
from .runtime import CbusRuntime

TO_REDACT = {"host", "address", CONF_REMOTE_API_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return non-sensitive project and connection diagnostics."""
    runtime: CbusRuntime = hass.data[DOMAIN][entry.entry_id]
    networks = []
    for network in runtime.project["networks"]:
        enabled, host, port, app = runtime.effective_connection(network)
        connection = runtime.connections.get(network["address"])
        unit_states = [
            runtime.illuminance_states[(network["address"], unit["address"])]
            for unit in network.get("units", [])
            if unit.get("supports_illuminance")
        ]
        error_counts = Counter(
            state.last_error for state in unit_states if state.last_error
        )
        remote_settings = runtime.remote_settings(network)
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
                "illuminance_units": len(unit_states),
                "illuminance_available": sum(
                    1 for state in unit_states if state.available
                ),
                "illuminance_errors": dict(error_counts),
                "remote_service": (
                    {
                        "scheme": remote_settings.scheme,
                        "host": remote_settings.host,
                        "port": remote_settings.port,
                        "username_configured": bool(remote_settings.username),
                        "verify_ssl": remote_settings.verify_ssl,
                    }
                    if remote_settings
                    else None
                ),
            }
        )
    return async_redact_data(
        {
            "entry": {
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            "project": {
                "name": runtime.project["project_name"],
                "id": runtime.project["project_id"],
                "db_version": runtime.project.get("db_version"),
                "schema_version": runtime.project.get("schema_version"),
                "network_count": len(runtime.project["networks"]),
                "illuminance_unit_count": sum(
                    len(network.get("units", []))
                    for network in runtime.project["networks"]
                ),
            },
            "illuminance_enabled": runtime.illuminance_enabled,
            "illuminance_poll_interval": runtime.illuminance_poll_interval,
            "networks": networks,
        },
        TO_REDACT,
    )
