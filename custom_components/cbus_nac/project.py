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


def classify_group(name: str, relay: bool = False) -> str:
    """Infer a conservative Home Assistant platform for a lighting group."""
    lower = name.casefold()
    if "motion" in lower and "light" not in lower:
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

        for unit_el in network_el.findall("Unit"):
            applications: list[int] = []
            app_pp = unit_el.find("PP[@Name='Application']")
            if app_pp is not None:
                applications = [v for v in _hex_values(app_pp.get("Value")) if v != 0xFF]
                app_use_counts.update(applications)

            unit_type = (unit_el.findtext("UnitType") or "").upper()
            if unit_type.startswith("REL"):
                group_pp = unit_el.find("PP[@Name='GroupAddress']")
                groups = [] if group_pp is None else _hex_values(group_pp.get("Value"))
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
                "unit_count": len(network_el.findall("Unit")),
            }
        )

    if not networks:
        raise ProjectError("No C-Bus networks were found in the project")

    return {
        "schema_version": 1,
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
        f"applications, {groups} project group records and {candidates} named entity "
        f"candidates with internal groups hidden.\n\n" + "\n".join(connection_lines)
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

    parts = [
        f"Networks added: {', '.join(map(str, added_networks)) if added_networks else 'none'}",
        f"Networks removed: {', '.join(map(str, removed_networks)) if removed_networks else 'none'}",
        f"Groups added: {len(new_keys - old_keys)}",
        f"Groups removed: {len(old_keys - new_keys)}",
        f"Groups renamed: {len(renamed)}",
        f"Groups reclassified: {len(reclassified)}",
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
