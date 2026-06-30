"""Shared C-Bus entity and device-registry support."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .runtime import CbusRuntime, GroupKey


def cbus_controller_identifier(
    runtime: CbusRuntime,
    network: dict[str, Any],
) -> tuple[str, str]:
    """Return the stable identifier for one NAC/CNI controller hub."""
    return (
        DOMAIN,
        f"{runtime.project['project_id']}:{network['address']}",
    )


def cbus_lights_identifier(
    runtime: CbusRuntime,
    network: dict[str, Any],
) -> tuple[str, str]:
    """Return the stable identifier for a controller's logical lights device."""
    return (
        DOMAIN,
        f"{runtime.project['project_id']}:{network['address']}:lights",
    )


def _configuration_url(
    runtime: CbusRuntime,
    network: dict[str, Any],
) -> str | None:
    """Return the controller URL using the effective connection settings."""
    settings = runtime.remote_settings(network)
    return settings.base_url if settings else None


def cbus_controller_device_info(
    runtime: CbusRuntime,
    network: dict[str, Any],
) -> DeviceInfo:
    """Return the root hub device for one imported C-Bus controller/network."""
    interface_type = network.get("interface", {}).get("type") or "CNI"
    model = "C-Bus NAC / CNI controller"
    if interface_type and str(interface_type).upper() != "CNI":
        model = f"C-Bus {interface_type} controller"

    return DeviceInfo(
        identifiers={cbus_controller_identifier(runtime, network)},
        name=network["name"],
        manufacturer="Schneider Electric / Clipsal",
        model=model,
        configuration_url=_configuration_url(runtime, network),
    )


def cbus_lights_device_info(
    runtime: CbusRuntime,
    network: dict[str, Any],
) -> DeviceInfo:
    """Return the child device containing all groups controlled by one hub."""
    return DeviceInfo(
        identifiers={cbus_lights_identifier(runtime, network)},
        name=f"{network['name']} Lights",
        manufacturer="Schneider Electric / Clipsal",
        model="C-Bus lighting groups",
        via_device=cbus_controller_identifier(runtime, network),
        configuration_url=_configuration_url(runtime, network),
    )


def cbus_unit_device_info(
    runtime: CbusRuntime,
    network: dict[str, Any],
    unit: dict[str, Any],
) -> DeviceInfo:
    """Return the child device for one physical C-Bus multisensor unit."""
    return DeviceInfo(
        identifiers={
            (
                DOMAIN,
                f"{runtime.project['project_id']}:{network['address']}:unit:{unit['address']}",
            )
        },
        name=unit["name"],
        manufacturer="Schneider Electric / Clipsal",
        model=(
            unit.get("catalog_number")
            or unit.get("unit_type")
            or "C-Bus sensor"
        ),
        sw_version=unit.get("firmware_version") or None,
        via_device=cbus_controller_identifier(runtime, network),
        configuration_url=_configuration_url(runtime, network),
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
        self._attr_device_info = cbus_lights_device_info(runtime, self.network)
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
