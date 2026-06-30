"""Runtime model for the C-Bus NAC integration."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_ENABLED,
    CONF_HOST_OVERRIDE,
    CONF_ILLUMINANCE_ENABLED,
    CONF_ILLUMINANCE_POLL_INTERVAL,
    CONF_INCLUDE_INTERNAL,
    CONF_MONITOR_APPLICATION,
    CONF_MOTION_SENSORS,
    CONF_PORT_OVERRIDE,
    CONF_REMOTE_API_PASSWORD,
    CONF_REMOTE_API_PORT,
    CONF_REMOTE_API_SCHEME,
    CONF_REMOTE_API_USERNAME,
    CONF_REMOTE_API_VERIFY_SSL,
    DEFAULT_ILLUMINANCE_ENABLED,
    DEFAULT_ILLUMINANCE_POLL_INTERVAL,
    DEFAULT_INCLUDE_INTERNAL,
    DEFAULT_MOTION_SENSORS,
    DEFAULT_REMOTE_API_PORT,
    DEFAULT_REMOTE_API_SCHEME,
    DEFAULT_REMOTE_API_USERNAME,
    DEFAULT_REMOTE_API_VERIFY_SSL,
    EVENT_CBUS,
)
from .protocol import CbusCniConnection, CbusLevelEvent
from .unit_parameter import (
    NacRemoteClient,
    NacRemoteSettings,
    UnitParameterError,
    light_level_alias,
)

_LOGGER = logging.getLogger(__name__)

GroupKey = tuple[int, int, int]
UnitKey = tuple[int, int]
ListenerKey = tuple[Any, ...]


@dataclass(slots=True)
class GroupState:
    """Last known state of one group."""

    is_on: bool | None = None
    brightness: int | None = None
    source: int | None = None


@dataclass(slots=True)
class IlluminanceState:
    """Last value read for one physical C-Bus sensor unit."""

    value: float | None = None
    available: bool = False
    last_updated: datetime | None = None
    last_error: str | None = None


@dataclass(slots=True)
class MotionState:
    """Last motion state derived from one physical PIR unit's C-Bus commands."""

    is_on: bool | None = None
    last_updated: datetime | None = None
    last_application: int | None = None
    last_group: int | None = None
    last_source: int | None = None


@dataclass(slots=True, frozen=True)
class MotionBinding:
    """Map one C-Bus group event to a physical PIR unit."""

    unit_key: UnitKey
    dedicated: bool


class CbusRuntime:
    """Own all CNI and NAC remote-service connections for one project."""

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
        self.illuminance_states: dict[UnitKey, IlluminanceState] = defaultdict(
            IlluminanceState
        )
        self.motion_states: dict[UnitKey, MotionState] = defaultdict(MotionState)
        self._listeners: dict[ListenerKey, set[Callable[[], None]]] = defaultdict(set)
        self._illuminance_tasks: list[asyncio.Task[None]] = []
        self._motion_bindings: dict[GroupKey, list[MotionBinding]] = defaultdict(list)
        self._motion_units: dict[UnitKey, dict[str, Any]] = {}
        self._build_motion_bindings()

    def _build_motion_bindings(self) -> None:
        """Index Toolkit PIR output programming for fast live-event matching."""
        for network in self.project["networks"]:
            network_address = network["address"]
            for unit in network.get("units", []):
                if not unit.get("supports_motion"):
                    continue
                unit_key = (network_address, unit["address"])
                self._motion_units[unit_key] = unit
                for group in unit.get("motion_groups", []):
                    key = (
                        network_address,
                        int(group["application"]),
                        int(group["group"]),
                    )
                    self._motion_bindings[key].append(
                        MotionBinding(unit_key, bool(group.get("dedicated")))
                    )

    @property
    def include_internal(self) -> bool:
        """Return whether generated/internal groups should be exposed."""
        return bool(
            self.entry.options.get(CONF_INCLUDE_INTERNAL, DEFAULT_INCLUDE_INTERNAL)
        )

    @property
    def motion_sensors(self) -> bool:
        """Return whether physical PIR units should be exposed as motion sensors."""
        return bool(self.entry.options.get(CONF_MOTION_SENSORS, DEFAULT_MOTION_SENSORS))

    @property
    def illuminance_enabled(self) -> bool:
        """Return whether Unit Parameter illuminance entities are enabled."""
        return bool(
            self.entry.options.get(
                CONF_ILLUMINANCE_ENABLED, DEFAULT_ILLUMINANCE_ENABLED
            )
        )

    @property
    def illuminance_poll_interval(self) -> int:
        """Return the remote-object refresh interval in seconds."""
        value = self.entry.options.get(
            CONF_ILLUMINANCE_POLL_INTERVAL, DEFAULT_ILLUMINANCE_POLL_INTERVAL
        )
        try:
            return max(15, int(value))
        except (TypeError, ValueError):
            return DEFAULT_ILLUMINANCE_POLL_INTERVAL

    def effective_connection(
        self, network: dict[str, Any]
    ) -> tuple[bool, str | None, int | None, int]:
        """Resolve project connection details and user overrides."""
        address = network["address"]
        interface = network["interface"]
        default_enabled = bool(interface.get("host"))
        enabled = bool(
            self.entry.options.get(f"{CONF_ENABLED}_{address}", default_enabled)
        )
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

    def remote_settings(self, network: dict[str, Any]) -> NacRemoteSettings | None:
        """Build the global remote-service settings for one network's NAC."""
        _enabled, host, _port, _app = self.effective_connection(network)
        if not host:
            return None
        scheme = str(
            self.entry.options.get(CONF_REMOTE_API_SCHEME, DEFAULT_REMOTE_API_SCHEME)
        ).casefold()
        if scheme not in ("http", "https"):
            scheme = DEFAULT_REMOTE_API_SCHEME
        default_port = 443 if scheme == "https" else DEFAULT_REMOTE_API_PORT
        try:
            port = int(self.entry.options.get(CONF_REMOTE_API_PORT, default_port))
        except (TypeError, ValueError):
            port = default_port
        return NacRemoteSettings(
            scheme=scheme,
            host=host,
            port=port,
            username=str(
                self.entry.options.get(
                    CONF_REMOTE_API_USERNAME, DEFAULT_REMOTE_API_USERNAME
                )
            ),
            password=str(self.entry.options.get(CONF_REMOTE_API_PASSWORD, "")),
            verify_ssl=bool(
                self.entry.options.get(
                    CONF_REMOTE_API_VERIFY_SSL, DEFAULT_REMOTE_API_VERIFY_SSL
                )
            ),
        )

    async def async_start(self) -> None:
        """Start all enabled direct CNI connections and optional sensor polling."""
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

        if self.illuminance_enabled:
            self._start_illuminance_pollers()

    async def async_stop(self) -> None:
        """Stop all network connections and polling tasks."""
        for task in self._illuminance_tasks:
            task.cancel()
        if self._illuminance_tasks:
            await asyncio.gather(*self._illuminance_tasks, return_exceptions=True)
        self._illuminance_tasks.clear()

        for connection in list(self.connections.values()):
            await connection.stop()
        self.connections.clear()

    def available(self, network: int) -> bool:
        """Return whether a network CNI is connected."""
        connection = self.connections.get(network)
        return bool(connection and connection.connected)

    def subscribe(
        self, key: ListenerKey, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Subscribe to a group, unit, or network availability update."""
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
        if not connection.connected:
            raise ConnectionError(f"Network {network} CNI is not connected")

        # Update Home Assistant immediately. The live SAL/MMI stream remains the
        # source of truth and will correct the state if the bus reports otherwise.
        self._apply_level(key, level, None)
        await connection.send_level(application, group, level, transition)

    def group_definitions(self, platform: str) -> list[dict[str, Any]]:
        """Return imported controllable groups that belong on a HA platform."""
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
                    # Motion-tagged groups are implementation details of physical
                    # PIR devices in v0.1.6. They no longer appear as separate
                    # entities under the controller/network device.
                    if group["platform"] == "binary_sensor":
                        continue
                    if group["platform"] != platform:
                        continue
                    result.append(
                        {
                            "network": network,
                            "application": application,
                            "group": group,
                        }
                    )
        return result

    def legacy_motion_group_definitions(self) -> list[dict[str, Any]]:
        """Return old group-backed motion entities so their registry entries can go."""
        return [
            {
                "network": network,
                "application": application,
                "group": group,
            }
            for network in self.project["networks"]
            for application in network["applications"]
            for group in application["groups"]
            if group.get("platform") == "binary_sensor" and group["address"] != 255
        ]

    def motion_definitions(self) -> list[dict[str, Any]]:
        """Return physical PIR units imported from Toolkit."""
        if not self.motion_sensors:
            return []
        return [
            {"network": network, "unit": unit}
            for network in self.project["networks"]
            for unit in network.get("units", [])
            if unit.get("supports_motion")
        ]

    def motion_available(self, key: UnitKey) -> bool:
        """Return whether a physical PIR can currently report motion."""
        unit = self._motion_units.get(key)
        return bool(
            unit
            and unit.get("motion_groups")
            and self.available(key[0])
        )

    def illuminance_definitions(self) -> list[dict[str, Any]]:
        """Return physical units imported as illuminance-capable sensors."""
        if not self.illuminance_enabled:
            return []
        return [
            {"network": network, "unit": unit}
            for network in self.project["networks"]
            for unit in network.get("units", [])
            if unit.get("supports_illuminance")
        ]

    def _start_illuminance_pollers(self) -> None:
        """Create one low-rate remote-object task for each usable NAC."""
        session = async_get_clientsession(self.hass)
        for index, network in enumerate(self.project["networks"]):
            units = [
                unit
                for unit in network.get("units", [])
                if unit.get("supports_illuminance")
            ]
            settings = self.remote_settings(network)
            if not units or settings is None:
                continue
            client = NacRemoteClient(session, settings)
            task = self.hass.async_create_task(
                self._poll_network_illuminance(network, units, client, index * 2),
                f"cbus_nac_illuminance_{network['address']}",
            )
            self._illuminance_tasks.append(task)

    async def _poll_network_illuminance(
        self,
        network: dict[str, Any],
        units: list[dict[str, Any]],
        client: NacRemoteClient,
        initial_delay: int,
    ) -> None:
        """Refresh all exported Unit Parameter objects from one NAC."""
        if initial_delay:
            await asyncio.sleep(initial_delay)
        while True:
            await self._refresh_network_illuminance(network, units, client)
            await asyncio.sleep(self.illuminance_poll_interval)

    async def _refresh_network_illuminance(
        self,
        network: dict[str, Any],
        units: list[dict[str, Any]],
        client: NacRemoteClient,
    ) -> None:
        network_address = network["address"]
        try:
            objects = await client.async_read_objects()
        except UnitParameterError as err:
            message = str(err)
            _LOGGER.debug(
                "Could not update C-Bus illuminance values for network %s: %s",
                network_address,
                message,
            )
            for unit in units:
                self._set_illuminance_error((network_address, unit["address"]), message)
            return

        for unit in units:
            key = (network_address, unit["address"])
            alias = light_level_alias(unit["address"])
            value = objects.get(alias)
            if value is None:
                self._set_illuminance_error(
                    key,
                    "Unit Parameter light-level object is not configured or exported "
                    f"on this NAC ({alias})",
                )
                continue
            state = self.illuminance_states[key]
            state.value = value
            state.available = True
            state.last_updated = datetime.now(UTC)
            state.last_error = None
            self._notify(key)

    def _set_illuminance_error(self, key: UnitKey, message: str) -> None:
        state = self.illuminance_states[key]
        changed = state.available or state.last_error != message
        state.available = False
        state.last_error = message
        if changed:
            self._notify(key)

    def _handle_event(self, network: int, event: CbusLevelEvent) -> None:
        key = (network, event.application, event.group)
        state = self.states[key]
        if event.is_on is not None:
            state.is_on = event.is_on
        if event.level is not None:
            state.brightness = event.level
            state.is_on = event.level > 0
        state.source = event.source

        self._handle_motion_event(key, event)

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

    def _handle_motion_event(self, key: GroupKey, event: CbusLevelEvent) -> None:
        """Update physical PIR state from its own outgoing group commands."""
        bindings = self._motion_bindings.get(key, [])
        if not bindings:
            return

        event_is_on = event.is_on
        if event.level is not None:
            event_is_on = event.level > 0
        if event_is_on is None:
            return

        for binding in bindings:
            unit_key = binding.unit_key
            if event.source is not None:
                # Live SAL includes the originating physical unit. This lets a
                # PIR use an ordinary light group without that light's manual
                # changes being misreported as motion.
                if event.source != unit_key[1]:
                    continue
            else:
                # MMI has no source unit. It is only safe for a dedicated motion
                # group that belongs to one physical PIR.
                if not binding.dedicated or len(bindings) != 1:
                    continue

            motion = self.motion_states[unit_key]
            motion.is_on = event_is_on
            motion.last_updated = datetime.now(UTC)
            motion.last_application = event.application
            motion.last_group = event.group
            motion.last_source = event.source
            self._notify(unit_key)

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
            if len(key) in (2, 3) and key[0] == network:
                self._notify(key)

    def _notify(self, key: ListenerKey) -> None:
        for callback in tuple(self._listeners.get(key, ())):
            callback()
