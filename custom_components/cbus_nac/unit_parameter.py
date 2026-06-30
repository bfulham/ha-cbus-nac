"""5500NAC remote-service helpers for C-Bus Unit Parameter objects."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import re
from typing import Any

from aiohttp import BasicAuth, ClientError, ClientResponseError, ClientSession

UNIT_PARAMETER_APPLICATION = 255
PARAMETER_LIGHT_LEVEL = 2


class UnitParameterError(RuntimeError):
    """Raised when a NAC remote-service request cannot be used."""


@dataclass(slots=True, frozen=True)
class NacRemoteSettings:
    """Connection settings for one NAC remote-service endpoint."""

    scheme: str
    host: str
    port: int
    username: str
    password: str
    verify_ssl: bool

    @property
    def base_url(self) -> str:
        """Return the remote-service base URL."""
        return f"{self.scheme}://{self.host}:{self.port}/scada-remote/"


_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def light_level_alias(unit_address: int) -> str:
    """Return the NAC-local composed address for a unit light-level parameter."""
    return f"0/{UNIT_PARAMETER_APPLICATION}/{unit_address}/{PARAMETER_LIGHT_LEVEL}"


def _coerce_number(value: Any) -> float | None:
    """Convert a remote object value to a finite number."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        match = _NUMBER_PATTERN.search(value.strip())
        if match is None:
            return None
        try:
            number = float(match.group(0))
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def parse_remote_objects(payload: str | bytes) -> dict[str, float]:
    """Parse the JSON returned by ``r=objects`` into numeric address values.

    Controller firmware variants have returned either a JSON list directly or a
    dictionary containing the list. This parser deliberately accepts both forms.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as err:
        raise UnitParameterError(f"Invalid JSON from NAC remote service: {err}") from err

    objects: Any = decoded
    if isinstance(decoded, dict):
        for key in ("objects", "object", "data", "result"):
            candidate = decoded.get(key)
            if isinstance(candidate, list):
                objects = candidate
                break
        else:
            # Some versions may return an address -> value mapping.
            mapped: dict[str, float] = {}
            for key, value in decoded.items():
                if not isinstance(key, str) or "/" not in key:
                    continue
                number = _coerce_number(value)
                if number is not None:
                    mapped[key.strip()] = number
            if mapped:
                return mapped
            raise UnitParameterError("NAC object response did not contain an object list")

    if not isinstance(objects, list):
        raise UnitParameterError("NAC object response was not a JSON list")

    result: dict[str, float] = {}
    for item in objects:
        if not isinstance(item, dict):
            continue
        address = item.get("address") or item.get("alias") or item.get("group")
        if not isinstance(address, str):
            continue
        value = item.get("data", item.get("value"))
        number = _coerce_number(value)
        if number is not None:
            result[address.strip()] = number
    return result


class NacRemoteClient:
    """Read exported objects through the 5500NAC JSON remote service."""

    def __init__(
        self,
        session: ClientSession,
        settings: NacRemoteSettings,
        timeout_seconds: float = 12.0,
    ) -> None:
        self._session = session
        self.settings = settings
        self._timeout_seconds = timeout_seconds

    async def async_read_objects(self) -> dict[str, float]:
        """Return all numeric remote objects indexed by composed address."""
        auth = (
            BasicAuth(self.settings.username, self.settings.password)
            if self.settings.username
            else None
        )
        ssl: bool | None = None
        if self.settings.scheme == "https" and not self.settings.verify_ssl:
            ssl = False

        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with self._session.get(
                    self.settings.base_url,
                    params={"m": "json", "r": "objects"},
                    auth=auth,
                    ssl=ssl,
                ) as response:
                    if response.status in (401, 403):
                        raise UnitParameterError(
                            "NAC remote service rejected the username or password"
                        )
                    response.raise_for_status()
                    return parse_remote_objects(await response.text())
        except TimeoutError as err:
            raise UnitParameterError("NAC remote-service request timed out") from err
        except ClientResponseError as err:
            raise UnitParameterError(
                f"NAC remote service returned HTTP {err.status}"
            ) from err
        except ClientError as err:
            raise UnitParameterError(f"Could not reach NAC remote service: {err}") from err
