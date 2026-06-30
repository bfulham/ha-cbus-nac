"""Config and options flows for C-Bus NAC."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import FileSelector, FileSelectorConfig

from .const import (
    CONF_ENABLED,
    CONF_HOST_OVERRIDE,
    CONF_INCLUDE_INTERNAL,
    CONF_MONITOR_APPLICATION,
    CONF_MOTION_SENSORS,
    CONF_NETWORK,
    CONF_PORT_OVERRIDE,
    CONF_PROJECT_FILE,
    CONF_PROJECT_HASH,
    CONF_PROJECT_ID,
    CONF_PROJECT_KEY,
    CONF_PROJECT_NAME,
    DEFAULT_INCLUDE_INTERNAL,
    DEFAULT_MOTION_SENSORS,
    DOMAIN,
)
from .project import ProjectError, parse_project_path, project_diff, project_summary
from .storage import async_load_project, async_save_project


class CbusNacConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle C-Bus NAC setup and project replacement."""

    VERSION = 1
    MINOR_VERSION = 0

    def __init__(self) -> None:
        self._project: dict[str, Any] | None = None
        self._old_project: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return CbusNacOptionsFlow(config_entry)

    def _parse_upload(self, upload_id: str) -> dict[str, Any]:
        with process_uploaded_file(self.hass, upload_id) as file_path:
            return parse_project_path(Path(file_path))

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Upload a Toolkit project."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._project = await self.hass.async_add_executor_job(
                    self._parse_upload, user_input[CONF_PROJECT_FILE]
                )
            except (OSError, ProjectError, ValueError):
                errors["base"] = "invalid_project"
            else:
                return await self.async_step_confirm()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROJECT_FILE): FileSelector(
                        FileSelectorConfig(
                            accept=".cbz,.xml,application/zip,application/xml,text/xml"
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm the imported connections and project."""
        assert self._project is not None
        if user_input is not None:
            await self.async_set_unique_id(self._project["project_id"].casefold())
            self._abort_if_unique_id_configured()
            project_key = await async_save_project(self.hass, self._project)
            return self.async_create_entry(
                title=self._project["project_name"],
                data={
                    CONF_PROJECT_KEY: project_key,
                    CONF_PROJECT_HASH: self._project["source_sha256"],
                    CONF_PROJECT_ID: self._project["project_id"],
                    CONF_PROJECT_NAME: self._project["project_name"],
                },
            )
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"summary": project_summary(self._project)},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Upload an updated Toolkit project."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if self._old_project is None:
            self._old_project = await async_load_project(
                self.hass, entry.data[CONF_PROJECT_KEY]
            )
        if user_input is not None:
            try:
                project = await self.hass.async_add_executor_job(
                    self._parse_upload, user_input[CONF_PROJECT_FILE]
                )
                if project["project_id"].casefold() != entry.data[CONF_PROJECT_ID].casefold():
                    errors["base"] = "different_project"
                else:
                    self._project = project
                    return await self.async_step_reconfigure_confirm()
            except (OSError, ProjectError, ValueError):
                errors["base"] = "invalid_project"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROJECT_FILE): FileSelector(
                        FileSelectorConfig(
                            accept=".cbz,.xml,application/zip,application/xml,text/xml"
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm replacement of the stored project."""
        assert self._project is not None
        assert self._old_project is not None
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            project_key = await async_save_project(self.hass, self._project)
            new_data = {
                **entry.data,
                CONF_PROJECT_KEY: project_key,
                CONF_PROJECT_HASH: self._project["source_sha256"],
                CONF_PROJECT_NAME: self._project["project_name"],
            }
            return self.async_update_reload_and_abort(
                entry,
                data=new_data,
                reason="reconfigure_successful",
            )
        return self.async_show_form(
            step_id="reconfigure_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "summary": project_diff(self._old_project, self._project)
            },
        )


class CbusNacOptionsFlow(OptionsFlow):
    """Edit network overrides and entity import behaviour."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        super().__init__()
        self._project: dict[str, Any] | None = None
        self._selected_network: dict[str, Any] | None = None

    async def _load_project(self) -> dict[str, Any]:
        if self._project is None:
            project = await async_load_project(
                self.hass, self.config_entry.data[CONF_PROJECT_KEY]
            )
            if project is None:
                raise RuntimeError("Stored C-Bus project is missing")
            self._project = project
        return self._project

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show options menu."""
        return self.async_show_menu(
            step_id="init", menu_options=["connections", "entities"]
        )

    async def async_step_connections(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a network to edit."""
        project = await self._load_project()
        choices = {
            str(network["address"]): (
                f"{network['address']} — {network['name']} "
                f"({network['interface'].get('address') or network['interface']['type']})"
            )
            for network in project["networks"]
        }
        if user_input is not None:
            selected = int(user_input[CONF_NETWORK])
            self._selected_network = next(
                network for network in project["networks"] if network["address"] == selected
            )
            return await self.async_step_connection()
        return self.async_show_form(
            step_id="connections",
            data_schema=vol.Schema({vol.Required(CONF_NETWORK): vol.In(choices)}),
        )

    async def async_step_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit one network connection."""
        assert self._selected_network is not None
        network = self._selected_network
        address = network["address"]
        options = dict(self.config_entry.options)
        default_enabled = bool(network["interface"].get("host"))
        monitor_choices = {
            str(app): next(
                (
                    application["name"]
                    for application in network["applications"]
                    if application["address"] == app
                ),
                f"Application {app}",
            )
            for app in network["active_applications"]
        }
        if not monitor_choices:
            monitor_choices = {"56": "Lighting (56)"}

        if user_input is not None:
            options[f"{CONF_ENABLED}_{address}"] = bool(user_input[CONF_ENABLED])
            host = str(user_input[CONF_HOST_OVERRIDE]).strip()
            port_text = str(user_input[CONF_PORT_OVERRIDE]).strip()
            if host:
                options[f"{CONF_HOST_OVERRIDE}_{address}"] = host
            else:
                options.pop(f"{CONF_HOST_OVERRIDE}_{address}", None)
            if port_text:
                try:
                    port = int(port_text)
                except ValueError:
                    port = 0
                if not 1 <= port <= 65535:
                    return self.async_show_form(
                        step_id="connection",
                        data_schema=self._connection_schema(network, monitor_choices),
                        errors={CONF_PORT_OVERRIDE: "invalid_port"},
                    )
                options[f"{CONF_PORT_OVERRIDE}_{address}"] = port
            else:
                options.pop(f"{CONF_PORT_OVERRIDE}_{address}", None)
            options[f"{CONF_MONITOR_APPLICATION}_{address}"] = int(
                user_input[CONF_MONITOR_APPLICATION]
            )
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="connection",
            data_schema=self._connection_schema(network, monitor_choices),
            description_placeholders={"network": network["name"]},
        )

    def _connection_schema(
        self, network: dict[str, Any], monitor_choices: dict[str, str]
    ) -> vol.Schema:
        address = network["address"]
        options = self.config_entry.options
        return vol.Schema(
            {
                vol.Required(
                    CONF_ENABLED,
                    default=options.get(
                        f"{CONF_ENABLED}_{address}",
                        bool(network["interface"].get("host")),
                    ),
                ): bool,
                vol.Optional(
                    CONF_HOST_OVERRIDE,
                    default=options.get(f"{CONF_HOST_OVERRIDE}_{address}", ""),
                ): str,
                vol.Optional(
                    CONF_PORT_OVERRIDE,
                    default=str(options.get(f"{CONF_PORT_OVERRIDE}_{address}", "")),
                ): str,
                vol.Required(
                    CONF_MONITOR_APPLICATION,
                    default=str(
                        options.get(
                            f"{CONF_MONITOR_APPLICATION}_{address}",
                            network.get("monitor_application", 56),
                        )
                    ),
                ): vol.In(monitor_choices),
            }
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit project entity filtering."""
        if user_input is not None:
            options = {
                **self.config_entry.options,
                CONF_INCLUDE_INTERNAL: bool(user_input[CONF_INCLUDE_INTERNAL]),
                CONF_MOTION_SENSORS: bool(user_input[CONF_MOTION_SENSORS]),
            }
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="entities",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INCLUDE_INTERNAL,
                        default=self.config_entry.options.get(
                            CONF_INCLUDE_INTERNAL, DEFAULT_INCLUDE_INTERNAL
                        ),
                    ): bool,
                    vol.Required(
                        CONF_MOTION_SENSORS,
                        default=self.config_entry.options.get(
                            CONF_MOTION_SENSORS, DEFAULT_MOTION_SENSORS
                        ),
                    ): bool,
                }
            ),
        )
