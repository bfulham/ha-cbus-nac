"""C-Bus binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import CbusGroupEntity
from .runtime import CbusRuntime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up motion groups and network connectivity sensors."""
    runtime: CbusRuntime = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = [
        CbusMotionSensor(runtime, definition)
        for definition in runtime.group_definitions("binary_sensor")
    ]
    entities.extend(
        CbusNetworkConnectivity(runtime, network)
        for network in runtime.project["networks"]
        if runtime.effective_connection(network)[1]
    )
    async_add_entities(entities)


class CbusMotionSensor(CbusGroupEntity, BinarySensorEntity):
    """A motion-named C-Bus group exposed read-only."""

    _attr_device_class = BinarySensorDeviceClass.MOTION

    @property
    def is_on(self) -> bool | None:
        """Return motion group state."""
        return self.runtime.states[self.key].is_on


class CbusNetworkConnectivity(BinarySensorEntity):
    """Connection state for one imported network."""

    _attr_has_entity_name = True
    _attr_name = "CNI connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_registry_enabled_default = True

    def __init__(self, runtime: CbusRuntime, network: dict) -> None:
        self.runtime = runtime
        self.network = network
        self._attr_unique_id = (
            f"{runtime.project['project_id']}:{network['address']}:connectivity"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{runtime.project['project_id']}:{network['address']}")},
            name=network["name"],
            manufacturer="Schneider Electric / Clipsal",
            model="C-Bus network via CNI",
        )
        self._unsubscribe = None

    @property
    def is_on(self) -> bool:
        """Return connection state."""
        return self.runtime.available(self.network["address"])

    @property
    def extra_state_attributes(self) -> dict:
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
