"""C-Bus light entities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_TRANSITION, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import CbusGroupEntity
from .runtime import CbusRuntime

# This integration has its own per-CNI command concurrency and confirmation
# tracking. Home Assistant must not serialize entity action calls at the
# platform level, otherwise a multi-light service call is sent one group at a
# time. A value of 0 disables the platform semaphore.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up imported C-Bus lights."""
    runtime: CbusRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CbusLight(runtime, definition)
        for definition in runtime.group_definitions("light")
    )


class CbusLight(CbusGroupEntity, LightEntity):
    """A C-Bus Lighting Application group."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def is_on(self) -> bool | None:
        """Return the last known on/off state."""
        return self.runtime.states[self.key].is_on

    @property
    def brightness(self) -> int | None:
        """Return exact brightness when learned from a command."""
        return self.runtime.states[self.key].brightness

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on or set brightness."""
        level = int(kwargs.get(ATTR_BRIGHTNESS, 255))
        transition = kwargs.get(ATTR_TRANSITION)
        await self.runtime.async_set_level(self.key, level, transition)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the group."""
        await self.runtime.async_set_level(self.key, 0, kwargs.get(ATTR_TRANSITION))
