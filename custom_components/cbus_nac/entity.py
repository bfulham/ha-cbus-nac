"""Shared C-Bus entity support."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .runtime import CbusRuntime, GroupKey


def cbus_unit_device_info(
    runtime: CbusRuntime,
    network: dict[str, Any],
    unit: dict[str, Any],
) -> DeviceInfo:
    """Return the shared Home Assistant device for one physical C-Bus unit."""
    project_id = runtime.project["project_id"]
    settings = runtime.remote_settings(network)
    return DeviceInfo(
        identifiers={(DOMAIN, f"{project_id}:{network['address']}:unit:{unit['address']}")},
        name=unit["name"],
        manufacturer="Schneider Electric / Clipsal",
        model=(
            unit.get("catalog_number")
            or unit.get("unit_type")
            or "C-Bus sensor"
        ),
        sw_version=unit.get("firmware_version") or None,
        via_device=(DOMAIN, f"{project_id}:{network['address']}"),
        configuration_url=settings.base_url if settings else None,
    )


class CbusGroupEntity(Entity):
    """Base entity backed by a C-Bus lighting group."""

    _attr_has_entity_name = True

    def __init__(self, runtime: CbusRuntime, definition: dict[str, Any]) -> None:
        self.runtime = runtime
        self.network = definition["network"]
        self.application = definition["application"]
        self.group = definition["group"]
        self.key: GroupKey = (
            self.network["address"],
            self.application["address"],
            self.group["address"],
        )
        self._attr_unique_id = (
            f"{runtime.project['project_id']}:{self.key[0]}:{self.key[1]}:{self.key[2]}"
        )
        self._attr_name = self.group["name"]
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{runtime.project['project_id']}:{self.network['address']}")
            },
            name=self.network["name"],
            manufacturer="Schneider Electric / Clipsal",
            model="C-Bus network via CNI",
            configuration_url=(
                f"http://{self.network['interface']['host']}"
                if self.network["interface"].get("host")
                else None
            ),
        )
        self._unsubscribe = None

    @property
    def available(self) -> bool:
        """Return network connection availability."""
        return self.runtime.available(self.network["address"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose C-Bus addressing for diagnostics and automations."""
        state = self.runtime.states[self.key]
        return {
            "cbus_network": self.key[0],
            "cbus_application": self.key[1],
            "cbus_group": self.key[2],
            "cbus_application_name": self.application["name"],
            "last_source_unit": state.source,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to push updates."""
        await super().async_added_to_hass()
        self._unsubscribe = self.runtime.subscribe(self.key, self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Remove the push subscription."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        await super().async_will_remove_from_hass()
