"""C-Bus physical sensor entities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfIlluminance
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .runtime import CbusRuntime, UnitKey
from .unit_parameter import light_level_alias


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up illuminance sensors imported from the Toolkit project."""
    runtime: CbusRuntime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CbusIlluminanceSensor(runtime, definition)
        for definition in runtime.illuminance_definitions()
    )


class CbusIlluminanceSensor(SensorEntity):
    """Ambient light read from a physical C-Bus unit through the NAC."""

    _attr_has_entity_name = True
    _attr_name = "Illuminance"
    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_native_unit_of_measurement = UnitOfIlluminance.LUX
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_should_poll = False

    def __init__(self, runtime: CbusRuntime, definition: dict[str, Any]) -> None:
        self.runtime = runtime
        self.network = definition["network"]
        self.unit = definition["unit"]
        self.key: UnitKey = (self.network["address"], self.unit["address"])
        project_id = runtime.project["project_id"]
        self._attr_unique_id = (
            f"{project_id}:{self.key[0]}:unit:{self.key[1]}:illuminance"
        )

        settings = runtime.remote_settings(self.network)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{project_id}:{self.key[0]}:unit:{self.key[1]}")},
            name=self.unit["name"],
            manufacturer="Schneider Electric / Clipsal",
            model=self.unit.get("catalog_number") or self.unit.get("unit_type") or "C-Bus sensor",
            sw_version=self.unit.get("firmware_version") or None,
            via_device=(DOMAIN, f"{project_id}:{self.key[0]}"),
            configuration_url=settings.base_url if settings else None,
        )
        self._unsubscribe = None

    @property
    def native_value(self) -> float | None:
        """Return the latest illuminance reading in lux."""
        return self.runtime.illuminance_states[self.key].value

    @property
    def available(self) -> bool:
        """Return whether the NAC supplied this Unit Parameter object."""
        return self.runtime.illuminance_states[self.key].available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the physical C-Bus address and polling status."""
        state = self.runtime.illuminance_states[self.key]
        return {
            "cbus_network": self.key[0],
            "cbus_unit": self.key[1],
            "cbus_unit_type": self.unit.get("unit_type"),
            "cbus_catalog_number": self.unit.get("catalog_number"),
            "nac_unit_parameter_alias": light_level_alias(self.key[1]),
            "source": "5500NAC Unit Parameter",
            "last_updated": (
                state.last_updated.isoformat() if state.last_updated else None
            ),
            "last_error": state.last_error,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to remote-service updates."""
        await super().async_added_to_hass()
        self._unsubscribe = self.runtime.subscribe(
            self.key, self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Remove the update subscription."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        await super().async_will_remove_from_hass()
