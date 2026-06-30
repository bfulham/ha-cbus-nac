"""C-Bus binary sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import cbus_controller_device_info, cbus_unit_device_info
from .runtime import CbusRuntime, UnitKey


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up physical PIR units and network connectivity sensors."""
    runtime: CbusRuntime = hass.data[DOMAIN][entry.entry_id]

    # v0.1.5 and earlier exposed motion-named groups as controller-level
    # binary sensors. Remove those registry entries now that motion belongs to
    # the physical sensor unit device.
    registry = er.async_get(hass)
    project_id = runtime.project["project_id"]
    for definition in runtime.legacy_motion_group_definitions():
        unique_id = (
            f"{project_id}:{definition['network']['address']}:"
            f"{definition['application']['address']}:"
            f"{definition['group']['address']}"
        )
        entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, unique_id)
        if entity_id:
            registry.async_remove(entity_id)

    entities: list[BinarySensorEntity] = [
        CbusUnitMotionSensor(runtime, definition)
        for definition in runtime.motion_definitions()
    ]
    entities.extend(
        CbusNetworkConnectivity(runtime, network)
        for network in runtime.project["networks"]
        if runtime.effective_connection(network)[1]
    )
    async_add_entities(entities)


class CbusUnitMotionSensor(BinarySensorEntity):
    """Motion state belonging to one physical C-Bus PIR unit."""

    _attr_has_entity_name = True
    _attr_name = "Motion"
    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_should_poll = False

    def __init__(self, runtime: CbusRuntime, definition: dict[str, Any]) -> None:
        self.runtime = runtime
        self.network = definition["network"]
        self.unit = definition["unit"]
        self.key: UnitKey = (self.network["address"], self.unit["address"])
        project_id = runtime.project["project_id"]
        self._attr_unique_id = (
            f"{project_id}:{self.key[0]}:unit:{self.key[1]}:motion"
        )
        self._attr_device_info = cbus_unit_device_info(
            runtime, self.network, self.unit
        )
        self._unsubscribe = None

    @property
    def is_on(self) -> bool | None:
        """Return the most recent motion state sent by this physical unit."""
        return self.runtime.motion_states[self.key].is_on

    @property
    def available(self) -> bool:
        """Return whether the PIR has a usable event path and connected CNI."""
        return self.runtime.motion_available(self.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the physical address and auto-discovered PIR outputs."""
        state = self.runtime.motion_states[self.key]
        groups = self.unit.get("motion_groups", [])
        attributes: dict[str, Any] = {
            "cbus_network": self.key[0],
            "cbus_unit": self.key[1],
            "cbus_unit_type": self.unit.get("unit_type"),
            "cbus_catalog_number": self.unit.get("catalog_number"),
            "motion_groups": [
                {
                    "application": group["application"],
                    "group": group["group"],
                    "name": group.get("name"),
                    "dedicated": bool(group.get("dedicated")),
                }
                for group in groups
            ],
            "source": "Physical PIR unit C-Bus commands",
            "last_updated": (
                state.last_updated.isoformat() if state.last_updated else None
            ),
            "last_application": state.last_application,
            "last_group": state.last_group,
            "last_source_unit": state.last_source,
        }
        if not groups:
            attributes["configuration_warning"] = (
                "This PIR has no programmed C-Bus output group. A 5753-series "
                "sensor cannot report motion to Home Assistant until at least one "
                "PIR function block issues a C-Bus group command. A separate "
                "dedicated Motion group is not required."
            )
        return attributes

    async def async_added_to_hass(self) -> None:
        """Subscribe to unit motion and network availability updates."""
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


class CbusNetworkConnectivity(BinarySensorEntity):
    """Connection state for one imported network."""

    _attr_has_entity_name = True
    _attr_name = "CNI connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(self, runtime: CbusRuntime, network: dict[str, Any]) -> None:
        self.runtime = runtime
        self.network = network
        self._attr_unique_id = (
            f"{runtime.project['project_id']}:{network['address']}:connectivity"
        )
        self._attr_device_info = cbus_controller_device_info(runtime, network)
        self._unsubscribe = None

    @property
    def is_on(self) -> bool:
        """Return connection state."""
        return self.runtime.available(self.network["address"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return effective connection details."""
        enabled, host, port, app = self.runtime.effective_connection(self.network)
        connection = self.runtime.connections.get(self.network["address"])
        return {
            "network_address": self.network["address"],
            "enabled": enabled,
            "host": host,
            "port": port,
            "monitor_application": app,
            "last_error": connection.last_error if connection else None,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to availability changes."""
        await super().async_added_to_hass()
        self._unsubscribe = self.runtime.subscribe(
            (self.network["address"],), self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Remove subscription."""
        if self._unsubscribe:
            self._unsubscribe()
        await super().async_will_remove_from_hass()
