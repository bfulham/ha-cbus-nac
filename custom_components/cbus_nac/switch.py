"""C-Bus switch entities."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import CbusGroupEntity
from .runtime import CbusRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up relay-like C-Bus groups."""
    runtime: CbusRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CbusSwitch(runtime, definition)
        for definition in runtime.group_definitions("switch")
    )


class CbusSwitch(CbusGroupEntity, SwitchEntity):
    """A relay or control group."""

    @property
    def is_on(self) -> bool | None:
        """Return state."""
        return self.runtime.states[self.key].is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Switch on."""
        await self.runtime.async_set_level(self.key, 255)

    async def async_turn_off(self, **kwargs) -> None:
        """Switch off."""
        await self.runtime.async_set_level(self.key, 0)
