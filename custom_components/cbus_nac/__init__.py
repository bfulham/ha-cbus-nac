"""C-Bus NAC direct integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .const import CONF_PROJECT_KEY, DOMAIN, PLATFORMS
from .runtime import CbusRuntime
from .storage import async_delete_project, async_load_project


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one imported C-Bus project."""
    project = await async_load_project(hass, entry.data[CONF_PROJECT_KEY])
    if project is None:
        raise ConfigEntryError(
            "The stored Toolkit project is missing. Reconfigure the integration and upload it again."
        )

    runtime = CbusRuntime(hass, entry, project)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await runtime.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a project and all CNI connections."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        runtime: CbusRuntime = hass.data[DOMAIN].pop(entry.entry_id)
        await runtime.async_stop()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after options or project changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the stored normalised project when the entry is deleted."""
    await async_delete_project(hass, entry.data[CONF_PROJECT_KEY])
