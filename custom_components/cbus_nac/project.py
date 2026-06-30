"""Toolkit project import and normalisation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import re
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_XML_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20
LIGHTING_APPLICATION_MIN = 0x30
LIGHTING_APPLICATION_MAX = 0x5F
ILLUMINANCE_UNIT_TYPES = {"SENPIRIB", "SENLL"}
ILLUMINANCE_CATALOG_NUMBERS = {"5753L", "5753PEIRL", "5031PE"}
MOTION_UNIT_TYPES = {"SENPIRIB"}
MOTION_CATALOG_NUMBERS = {"5753L", "5753PEIRL"}
_MOTION_NAME_TOKENS = ("motion", "occupancy", "pir")

_INTERNAL_PATTERNS = (
    re.compile(r"^z", re.IGNORECASE),
    re.compile(r"^group\s+\d+$", re.IGNORECASE),
    re.compile(r"^d\d+[ab]\s+(?:group|fitting)\s*\d+$", re.IGNORECASE),
    re.compile(r"^d\d+[ab]\s+broadcast$", re.IGNORECASE),
)


class ProjectError(ValueError):
    """Raised when a Toolkit project cannot be imported."""


@dataclass(slots=True, frozen=True)
class ParsedInterface:
    """A project network interface."""

    interface_type: str
    address: str
    host: str | None
    port: int | None


def _safe_int(value: str | None, default: int = 0) -> int:
    try:
        return int((value or "").strip(), 0)
    except (TypeError, ValueError):
        return default


def _hex_values(value: str | None) -> list[int]:
    result: list[int] = []
    for token in (value or "").split():
        try:
            result.append(int(token, 16))
        except ValueError:
            continue
    return result


def _pp_element(unit: ET.Element, name: str) -> ET.Element | None:
    return unit.find(f"PP[@Name='{name}']")


def _pp_values(unit: ET.Element, name: str) -> list[int]:
    element = _pp_element(unit, name)
    return [] if element is None else _hex_values(element.get("Value"))


def _pp_int(unit: ET.Element, name: str, default: int = 0) -> int:
    values = _pp_values(unit, name)
    return values[0] if values else default


def _parse_interface(interface: ET.Element | None) -> ParsedInterface:
    if interface is None:
        return ParsedInterface("None", "", None, None)

    interface_type = (interface.findtext("InterfaceType") or "Unknown").strip()
    address = (interface.findtext("InterfaceAddress") or "").strip()
    host: str | None = None
    port: int | None = None

    if interface_type.upper() == "CNI" and address:
        if address.startswith("[") and "]:" in address:
            host_part, port_part = address.rsplit(":", 1)
            host = host_part[1:-1]
        elif ":" in address:
            host, port_part = address.rsplit(":", 1)
        else:
            host, port_part = address, "10001"
        try:
            port = int(port_part)
        except ValueError:
            host, port = address, 10001

    return ParsedInterface(interface_type, address, host, port)


def is_internal_group(name: str) -> bool:
    """Return whether a project group looks like generated/internal configuration."""
    cleaned = name.strip()
    if not cleaned or cleaned == "<Unused>" or "DONT USE" in cleaned.upper():
        return True
    return any(pattern.search(cleaned) for pattern in _INTERNAL_PATTERNS)


def is_motion_group_name(name: str) -> bool:
    """Return whether a tag explicitly describes PIR/occupancy state."""
    lower = name.casefold()
    return any(token in lower for token in _MOTION_NAME_TOKENS)


def classify_group(name: str, relay: bool = False) -> str:
    """Infer a conservative Home Assistant platform for a lighting group."""
    lower = name.casefold()
    if is_motion_group_name(name) and "light" not in lower:
        return "binary_sensor"
    if relay or any(
        token in lower
        for token in (
            "relay",
            "master off",
            "pir enable",
            "pir disable",
            "dlt trigger",
            "trigger onoff",
        )
    ):
        return "switch"
    return "light"


def _resolve_motion_groups(
    unit: dict[str, Any],
    group_lookup: dict[tuple[int, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve PIR output blocks into group addresses from Toolkit programming.

    A 5753-series PIR reports motion by issuing Lighting Application commands from
    one or more programmed PIR blocks. Prefer explicitly named Motion/PIR groups,
    then blocks active in both light and dark conditions, and finally all active PIR
    output blocks. This means a dedicated Motion group is not required: an existing
    light-control group can still be used to derive per-unit motion from the source
    unit address in live C-Bus traffic.
    """
    applications: list[int] = unit.pop("_applications", [])
    groups: list[int] = unit.pop("_group_addresses", [])
    light_mask = int(unit.pop("_pir_light_movement", 0))
    dark_mask = int(unit.pop("_pir_dark_movement", 0))
    second_app_mask = int(unit.pop("_second_application_blocks", 0))

    if not applications or not groups:
        return []

    union_mask = light_mask | dark_mask
    common_mask = light_mask & dark_mask
    candidates: list[dict[str, Any]] = []

    for block, group in enumerate(groups[:8]):
        bit = 1 << block
        if group == 0xFF or not union_mask & bit:
            continue
        use_second = bool(second_app_mask & bit) and len(applications) > 1
        application = applications[1] if use_second else applications[0]
        if application == 0xFF:
            continue
        project_group = group_lookup.get((application, group), {})
        name = str(project_group.get("name") or f"Group {group}")
        candidates.append(
            {
                "application": application,
                "group": group,
                "name": name,
                "block": block,
                "dedicated": is_motion_group_name(name),
                "active_in_light": bool(light_mask & bit),
                "active_in_dark": bool(dark_mask & bit),
                "active_in_both": bool(common_mask & bit),
            }
        )

    explicit = [candidate for candidate in candidates if candidate["dedicated"]]
    common = [candidate for candidate in candidates if candidate["active_in_both"]]
    selected = explicit or common or candidates

    unique: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for candidate in selected:
        key = (candidate["application"], candidate["group"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _read_project_xml(path: Path) -> tuple[bytes, str]:
    size = path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise ProjectError("Project upload is too large")

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise ProjectError("Project archive contains too many files")
            xml_members = [m for m in members if m.filename.casefold().endswith(".xml")]
            if not xml_members:
                raise ProjectError("No XML project was found in the CBZ archive")
            xml_member = max(xml_members, key=lambda item: item.file_size)
            if xml_member.file_size > MAX_XML_BYTES:
                raise ProjectError("Expanded project XML is too large")
            if ".." in Path(xml_member.filename).parts:
                raise ProjectError("Unsafe archive path")
            return archive.read(xml_member), xml_member.filename

    raw = path.read_bytes()
    if len(raw) > MAX_XML_BYTES:
        raise ProjectError("Project XML is too large")
    return raw, path.name


def parse_project_path(path: Path) -> dict[str, Any]:
    """Parse a Toolkit CBZ/XML file into a compact, versioned model."""
    raw, source_name = _read_project_xml(path)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ProjectError("DTD and XML entity declarations are not permitted")

    digest = hashlib.sha256(raw).hexdigest()
    try:
        root = ET.parse(io.BytesIO(raw)).getroot()
    except ET.ParseError as err:
        raise ProjectError(f"Invalid Toolkit XML: {err}") from err

    project_el = root.find("Project") if root.tag != "Project" else root
    if project_el is None:
        raise ProjectError("The upload does not contain a C-Bus Project element")

    project_name = (project_el.findtext("TagName") or "C-Bus Project").strip()
    project_id = (project_el.findtext("Address") or project_name).strip()
    networks: list[dict[str, Any]] = []

    for network_el in project_el.findall("Network"):
        network_address = _safe_int(network_el.findtext("Address"), -1)
        if not 0 <= network_address <= 255:
            continue
        network_name = (
            network_el.findtext("TagName") or f"Network {network_address}"
        ).strip()
        interface = _parse_interface(network_el.find("Interface"))

        app_use_counts: Counter[int] = Counter()
        relay_groups: set[tuple[int, int]] = set()
        unit_models: list[dict[str, Any]] = []

        for unit_el in network_el.findall("Unit"):
            applications = [value for value in _pp_values(unit_el, "Application") if value != 0xFF]
            app_use_counts.update(applications)

            unit_address = _safe_int(unit_el.findtext("Address"), -1)
            unit_type = (unit_el.findtext("UnitType") or "").strip().upper()
            catalog_number = (unit_el.findtext("CatalogNumber") or "").strip().upper()
            if 0 <= unit_address <= 255:
                supports_illuminance = (
                    unit_type in ILLUMINANCE_UNIT_TYPES
                    or catalog_number in ILLUMINANCE_CATALOG_NUMBERS
                )
                supports_motion = (
                    unit_type in MOTION_UNIT_TYPES
                    or catalog_number in MOTION_CATALOG_NUMBERS
                )
                if supports_illuminance or supports_motion:
                    unit_models.append(
                        {
                            "address": unit_address,
                            "name": (
                                unit_el.findtext("TagName") or f"Unit {unit_address}"
                            ).strip(),
                            "unit_type": unit_type,
                            "catalog_number": catalog_number,
                            "firmware_version": (
                                unit_el.findtext("FirmwareVersion") or ""
                            ).strip(),
                            "supports_illuminance": supports_illuminance,
                            "supports_motion": supports_motion,
                            "applications": applications,
                            "_applications": applications,
                            "_group_addresses": _pp_values(unit_el, "GroupAddress"),
                            "_pir_light_movement": _pp_int(
                                unit_el, "PIRLightMovement"
                            ),
                            "_pir_dark_movement": _pp_int(
                                unit_el, "PIRDarkMovement"
                            ),
                            "_second_application_blocks": _pp_int(
                                unit_el, "SecondApplicationBlocks"
                            ),
                        }
                    )

            if unit_type.startswith("REL"):
                groups = _pp_values(unit_el, "GroupAddress")
                for app in applications:
                    for group in groups:
                        if group != 0xFF:
                            relay_groups.add((app, group))

        application_models: list[dict[str, Any]] = []
        for application_el in network_el.findall("Application"):
            app_address = _safe_int(application_el.findtext("Address"), -1)
            if not LIGHTING_APPLICATION_MIN <= app_address <= LIGHTING_APPLICATION_MAX:
                continue
            groups: list[dict[str, Any]] = []
            for group_el in application_el.findall("Group"):
                group_address = _safe_int(group_el.findtext("Address"), -1)
                if not 0 <= group_address <= 255:
                    continue
                name = (
                    group_el.findtext("TagName") or f"Group {group_address}"
                ).strip()
                levels = [
                    {
                        "value": _safe_int(level_el.get("Value"), 0),
                        "name": (
                            level_el.findtext("TagName")
                            or f"Level {_safe_int(level_el.get('Value'), 0)}"
                        ).strip(),
                    }
                    for level_el in group_el.findall("Level")
                ]
                relay = (app_address, group_address) in relay_groups
                groups.append(
                    {
                        "address": group_address,
                        "name": name,
                        "internal": is_internal_group(name),
                        "platform": classify_group(name, relay),
                        "relay": relay,
                        "levels": levels,
                    }
                )

            application_models.append(
                {
                    "address": app_address,
                    "name": (
                        application_el.findtext("TagName")
                        or f"Application {app_address}"
                    ).strip(),
                    "referenced_by_units": app_use_counts.get(app_address, 0),
                    "groups": groups,
                }
            )

        group_lookup = {
            (application["address"], group["address"]): group
            for application in application_models
            for group in application["groups"]
        }
        for unit in unit_models:
            unit["motion_groups"] = (
                _resolve_motion_groups(unit, group_lookup)
                if unit.get("supports_motion")
                else []
            )
            # Clean up temporary parser-only keys for non-motion units too.
            unit.pop("_applications", None)
            unit.pop("_group_addresses", None)
            unit.pop("_pir_light_movement", None)
            unit.pop("_pir_dark_movement", None)
            unit.pop("_second_application_blocks", None)

        active_apps = [
            app["address"]
            for app in sorted(
                application_models,
                key=lambda item: (-item["referenced_by_units"], item["address"]),
            )
            if app["referenced_by_units"] > 0
        ]
        if not active_apps:
            active_apps = [app["address"] for app in application_models]

        networks.append(
            {
                "address": network_address,
                "name": network_name,
                "interface": {
                    "type": interface.interface_type,
                    "address": interface.address,
                    "host": interface.host,
                    "port": interface.port,
                },
                "active_applications": active_apps,
                "monitor_application": active_apps[0] if active_apps else 56,
                "applications": application_models,
                "units": unit_models,
                "unit_count": len(network_el.findall("Unit")),
            }
        )

    if not networks:
        raise ProjectError("No C-Bus networks were found in the project")

    return {
        "schema_version": 3,
        "source_name": source_name,
        "source_sha256": digest,
        "db_version": (root.findtext("DBVersion") or "").strip(),
        "project_name": project_name,
        "project_id": project_id,
        "networks": networks,
    }


def project_summary(project: dict[str, Any]) -> str:
    """Build a concise human-readable project summary."""
    networks = project["networks"]
    cni = [n for n in networks if n["interface"]["host"]]
    serial = [n for n in networks if not n["interface"]["host"]]
    applications = sum(len(n["active_applications"]) for n in networks)
    groups = sum(
        len(app["groups"])
        for n in networks
        for app in n["applications"]
        if app["address"] in n["active_applications"]
    )
    candidates = sum(
        1
        for n in networks
        for app in n["applications"]
        if app["address"] in n["active_applications"]
        for group in app["groups"]
        if group["address"] != 255 and not group["internal"]
    )
    illuminance_units = sum(
        1
        for network in networks
        for unit in network.get("units", [])
        if unit.get("supports_illuminance")
    )
    motion_units = sum(
        1
        for network in networks
        for unit in network.get("units", [])
        if unit.get("supports_motion")
    )
    motion_without_output = sum(
        1
        for network in networks
        for unit in network.get("units", [])
        if unit.get("supports_motion") and not unit.get("motion_groups")
    )
    connection_lines = [
        f"• {n['address']} — {n['name']}: {n['interface']['host']}:{n['interface']['port']}"
        for n in cni
    ]
    if serial:
        connection_lines.extend(
            f"• {n['address']} — {n['name']}: {n['interface']['type']} (manual TCP override required)"
            for n in serial
        )
    return (
        f"Project **{project['project_name']}** contains {len(networks)} networks, "
        f"{len(cni)} detected TCP CNI connections, {applications} referenced lighting "
        f"applications, {groups} project group records, {candidates} named group entity "
        f"candidates, {illuminance_units} illuminance-capable units and {motion_units} "
        f"physical PIR units ({motion_without_output} with no reportable PIR output group).\n\n"
        + "\n".join(connection_lines)
    )


def project_diff(old: dict[str, Any], new: dict[str, Any]) -> str:
    """Build a project update summary without changing address-based identity."""
    old_networks = {n["address"]: n for n in old["networks"]}
    new_networks = {n["address"]: n for n in new["networks"]}
    added_networks = sorted(set(new_networks) - set(old_networks))
    removed_networks = sorted(set(old_networks) - set(new_networks))

    connection_changes: list[str] = []
    for address in sorted(set(old_networks) & set(new_networks)):
        old_if = old_networks[address]["interface"]
        new_if = new_networks[address]["interface"]
        old_endpoint = (old_if.get("type"), old_if.get("host"), old_if.get("port"))
        new_endpoint = (new_if.get("type"), new_if.get("host"), new_if.get("port"))
        if old_endpoint != new_endpoint:
            connection_changes.append(
                f"{address}: {old_if.get('address') or old_if.get('type')} → "
                f"{new_if.get('address') or new_if.get('type')}"
            )

    def group_map(project: dict[str, Any]) -> dict[tuple[int, int, int], dict[str, Any]]:
        return {
            (network["address"], application["address"], group["address"]): group
            for network in project["networks"]
            for application in network["applications"]
            for group in application["groups"]
        }

    old_groups = group_map(old)
    new_groups = group_map(new)
    old_keys = set(old_groups)
    new_keys = set(new_groups)
    common = old_keys & new_keys
    renamed = [
        (key, old_groups[key]["name"], new_groups[key]["name"])
        for key in sorted(common)
        if old_groups[key]["name"] != new_groups[key]["name"]
    ]
    reclassified = [
        key
        for key in common
        if old_groups[key].get("platform") != new_groups[key].get("platform")
    ]

    def unit_map(project: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
        return {
            (network["address"], unit["address"]): unit
            for network in project["networks"]
            for unit in network.get("units", [])
        }

    old_units = unit_map(old)
    new_units = unit_map(new)
    old_illum = {key for key, unit in old_units.items() if unit.get("supports_illuminance")}
    new_illum = {key for key, unit in new_units.items() if unit.get("supports_illuminance")}
    old_motion = {key for key, unit in old_units.items() if unit.get("supports_motion")}
    new_motion = {key for key, unit in new_units.items() if unit.get("supports_motion")}
    motion_mapping_changes = sum(
        1
        for key in old_motion & new_motion
        if old_units[key].get("motion_groups", [])
        != new_units[key].get("motion_groups", [])
    )

    parts = [
        f"Networks added: {', '.join(map(str, added_networks)) if added_networks else 'none'}",
        f"Networks removed: {', '.join(map(str, removed_networks)) if removed_networks else 'none'}",
        f"Groups added: {len(new_keys - old_keys)}",
        f"Groups removed: {len(old_keys - new_keys)}",
        f"Groups renamed: {len(renamed)}",
        f"Groups reclassified: {len(reclassified)}",
        f"Illuminance units added: {len(new_illum - old_illum)}",
        f"Illuminance units removed: {len(old_illum - new_illum)}",
        f"Motion units added: {len(new_motion - old_motion)}",
        f"Motion units removed: {len(old_motion - new_motion)}",
        f"Motion output mappings changed: {motion_mapping_changes}",
    ]
    if renamed:
        preview = "; ".join(
            f"{net}/{app}/{group}: {old_name} → {new_name}"
            for (net, app, group), old_name, new_name in renamed[:10]
        )
        if len(renamed) > 10:
            preview += f"; and {len(renamed) - 10} more"
        parts.append("Rename preview: " + preview)
    if connection_changes:
        parts.append("Connection changes: " + "; ".join(connection_changes))
    return "\n\n".join(parts)
