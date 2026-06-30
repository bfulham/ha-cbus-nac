"""C-Bus NAC direct integration."""

from __future__ import annotations

from contextlib import suppress

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr

from .const import CONF_PROJECT_KEY, DOMAIN, PLATFORMS
from .entity import cbus_controller_device_info
from .runtime import CbusRuntime
from .storage import async_delete_project, async_load_project


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one imported C-Bus project."""
    project = await async_load_project(hass, entry.data[CONF_PROJECT_KEY])
    if project is None:
        raise ConfigEntryError(
            "The stored Toolkit project is missing. Reconfigure the integration and upload it again."
        )

    domain_data = hass.data.setdefault(DOMAIN, {})

    # A failed or interrupted setup must never leave an old runtime connected to
    # the single-client CNI ports. Stop any stale runtime before replacing it.
    stale_runtime: CbusRuntime | None = domain_data.pop(entry.entry_id, None)
    if stale_runtime is not None:
        await stale_runtime.async_stop()

    runtime = CbusRuntime(hass, entry, project)
    domain_data[entry.entry_id] = runtime

    # Child devices use via_device to form a controller -> lights/multisensors
    # topology. Register every imported controller before entity platforms are
    # forwarded so Home Assistant can resolve those parent identifiers.
    device_registry = dr.async_get(hass)
    for network in project["networks"]:
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **cbus_controller_device_info(runtime, network),
        )

    try:
        await runtime.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        # Platform import/setup errors can occur after the CNI tasks have started.
        # Clean them up immediately so a retry does not compete with an orphaned
        # connection manager for the NAC's single CNI client slot.
        await runtime.async_stop()
        with suppress(Exception):
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        domain_data.pop(entry.entry_id, None)
        raise

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
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
