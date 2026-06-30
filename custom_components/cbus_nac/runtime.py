"""Runtime model for the C-Bus NAC integration."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENABLED,
    CONF_HOST_OVERRIDE,
    CONF_INCLUDE_INTERNAL,
    CONF_MONITOR_APPLICATION,
    CONF_MOTION_SENSORS,
    CONF_PORT_OVERRIDE,
    DEFAULT_INCLUDE_INTERNAL,
    DEFAULT_MOTION_SENSORS,
    EVENT_CBUS,
)
from .protocol import CbusCniConnection, CbusLevelEvent

_LOGGER = logging.getLogger(__name__)

GroupKey = tuple[int, int, int]


@dataclass(slots=True)
class GroupState:
    """Last known state of one group."""

    is_on: bool | None = None
    brightness: int | None = None
    source: int | None = None


class CbusRuntime:
    """Own all CNI connections for one imported Toolkit project."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        project: dict[str, Any],
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.project = project
        self.connections: dict[int, CbusCniConnection] = {}
        self.states: dict[GroupKey, GroupState] = defaultdict(GroupState)
        self._listeners: dict[GroupKey | tuple[int], set[Callable[[], None]]] = defaultdict(set)

    @property
    def include_internal(self) -> bool:
        """Return whether generated/internal groups should be exposed."""
        return bool(
            self.entry.options.get(CONF_INCLUDE_INTERNAL, DEFAULT_INCLUDE_INTERNAL)
        )

    @property
    def motion_sensors(self) -> bool:
        """Return whether motion-named groups are binary sensors."""
        return bool(self.entry.options.get(CONF_MOTION_SENSORS, DEFAULT_MOTION_SENSORS))

    def effective_connection(self, network: dict[str, Any]) -> tuple[bool, str | None, int | None, int]:
        """Resolve project connection details and user overrides."""
        address = network["address"]
        interface = network["interface"]
        default_enabled = bool(interface.get("host"))
        enabled = bool(self.entry.options.get(f"{CONF_ENABLED}_{address}", default_enabled))
        host_override = str(
            self.entry.options.get(f"{CONF_HOST_OVERRIDE}_{address}", "")
        ).strip()
        port_override = self.entry.options.get(f"{CONF_PORT_OVERRIDE}_{address}")
        host = host_override or interface.get("host")
        port = int(port_override) if port_override else interface.get("port")
        monitor_app = int(
            self.entry.options.get(
                f"{CONF_MONITOR_APPLICATION}_{address}",
                network.get("monitor_application", 56),
            )
        )
        return enabled, host, port, monitor_app

    async def async_start(self) -> None:
        """Start all enabled direct CNI connections."""
        for network in self.project["networks"]:
            address = network["address"]
            enabled, host, port, monitor_app = self.effective_connection(network)
            if not enabled or not host or not port:
                continue
            connection = CbusCniConnection(
                host,
                port,
                monitor_app,
                lambda event, net=address: self._handle_event(net, event),
                lambda available, net=address: self._handle_availability(net, available),
            )
            self.connections[address] = connection
            connection.start()

    async def async_stop(self) -> None:
        """Stop all network connections."""
        for connection in list(self.connections.values()):
            await connection.stop()
        self.connections.clear()

    def available(self, network: int) -> bool:
        """Return whether a network CNI is connected."""
        connection = self.connections.get(network)
        return bool(connection and connection.connected)

    def subscribe(self, key: GroupKey | tuple[int], callback: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to a group or network availability update."""
        self._listeners[key].add(callback)

        def unsubscribe() -> None:
            self._listeners[key].discard(callback)

        return unsubscribe

    async def async_set_level(
        self,
        key: GroupKey,
        level: int,
        transition: float | None = None,
    ) -> None:
        """Send a level through the correct network CNI."""
        network, application, group = key
        connection = self.connections.get(network)
        if connection is None:
            raise ConnectionError(f"Network {network} has no enabled TCP CNI connection")
        await connection.send_level(application, group, level, transition)
        self._apply_level(key, level, None)

    def group_definitions(self, platform: str) -> list[dict[str, Any]]:
        """Return imported groups that should be exposed on a platform."""
        result: list[dict[str, Any]] = []
        for network in self.project["networks"]:
            active = set(network["active_applications"])
            for application in network["applications"]:
                if application["address"] not in active:
                    continue
                for group in application["groups"]:
                    if group["address"] == 255:
                        continue
                    if group["internal"] and not self.include_internal:
                        continue
                    selected_platform = group["platform"]
                    if selected_platform == "binary_sensor" and not self.motion_sensors:
                        selected_platform = "light"
                    if selected_platform != platform:
                        continue
                    result.append(
                        {
                            "network": network,
                            "application": application,
                            "group": group,
                        }
                    )
        return result

    def _handle_event(self, network: int, event: CbusLevelEvent) -> None:
        key = (network, event.application, event.group)
        state = self.states[key]
        if event.is_on is not None:
            state.is_on = event.is_on
        if event.level is not None:
            state.brightness = event.level
            state.is_on = event.level > 0
        state.source = event.source
        self.hass.bus.async_fire(
            EVENT_CBUS,
            {
                "network": network,
                "application": event.application,
                "group": event.group,
                "level": event.level,
                "is_on": event.is_on,
                "source": event.source,
                "ramp_seconds": event.ramp_seconds,
                "from_mmi": event.from_mmi,
            },
        )
        self._notify(key)

    def _apply_level(self, key: GroupKey, level: int, source: int | None) -> None:
        state = self.states[key]
        state.is_on = level > 0
        state.brightness = level
        state.source = source
        self._notify(key)

    def _handle_availability(self, network: int, available: bool) -> None:
        _LOGGER.info("C-Bus network %s availability changed to %s", network, available)
        self._notify((network,))
        for key in list(self._listeners):
            if len(key) == 3 and key[0] == network:
                self._notify(key)

    def _notify(self, key: GroupKey | tuple[int]) -> None:
        for callback in tuple(self._listeners.get(key, ())):
            callback()
