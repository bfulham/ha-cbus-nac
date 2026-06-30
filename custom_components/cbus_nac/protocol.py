"""Minimal asynchronous direct C-Bus CNI protocol support.

This implements the public C-Bus Lighting Control Quick Start command subset:
ON, OFF, RAMP TO LEVEL, received SAL messages, confirmations and standard MMI.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import itertools
import logging
import re
from typing import Final

_LOGGER = logging.getLogger(__name__)

_CONFIRM_RE: Final = re.compile(r"^([g-z])([.#$%])")
_RAMP_SECONDS: Final[dict[int, float]] = {
    0x02: 0,
    0x0A: 4,
    0x12: 8,
    0x1A: 12,
    0x22: 20,
    0x2A: 30,
    0x32: 40,
    0x3A: 60,
    0x42: 90,
    0x4A: 120,
    0x52: 180,
    0x5A: 300,
    0x62: 420,
    0x6A: 600,
    0x72: 900,
    0x7A: 1020,
}


@dataclass(slots=True, frozen=True)
class CbusLevelEvent:
    """A decoded C-Bus group state event."""

    application: int
    group: int
    level: int | None
    is_on: bool | None
    source: int | None = None
    ramp_seconds: float | None = None
    from_mmi: bool = False


def checksum(data: bytes) -> int:
    """Calculate a C-Bus two's-complement checksum."""
    return (-sum(data)) & 0xFF


def encode_lighting_command(
    application: int,
    group: int,
    level: int,
    transition: float | None = None,
) -> bytes:
    """Encode one direct CNI lighting command without confirmation suffix."""
    if not 0 <= application <= 255:
        raise ValueError("application must be 0..255")
    if not 0 <= group <= 254:
        raise ValueError("group must be 0..254")
    if not 0 <= level <= 255:
        raise ValueError("level must be 0..255")

    if level == 0 and not transition:
        payload = bytes((0x05, application, 0x00, 0x01, group))
    elif level == 255 and not transition:
        payload = bytes((0x05, application, 0x00, 0x79, group))
    else:
        rate = transition_to_ramp_code(transition)
        payload = bytes((0x05, application, 0x00, rate, group, level))
    packet = payload + bytes((checksum(payload),))
    return b"\\" + packet.hex().upper().encode("ascii")


def transition_to_ramp_code(seconds: float | None) -> int:
    """Map a Home Assistant transition to the nearest C-Bus ramp-rate code."""
    if seconds is None or seconds <= 0:
        return 0x02
    return min(_RAMP_SECONDS, key=lambda code: abs(_RAMP_SECONDS[code] - seconds))


def parse_cni_line(
    line: bytes | bytearray | memoryview | str,
) -> list[CbusLevelEvent]:
    """Decode a CNI line into zero or more group events."""
    text = (
        line
        if isinstance(line, str)
        else bytes(line).decode("ascii", errors="ignore")
    )
    text = text.strip().lstrip("\\")
    if not text or _CONFIRM_RE.match(text):
        return []
    if len(text) % 2 or not all(c in "0123456789abcdefABCDEF" for c in text):
        return []
    try:
        data = bytes.fromhex(text)
    except ValueError:
        return []
    if len(data) < 2 or sum(data) & 0xFF:
        return []

    if data[0] >= 0xC0:
        return _parse_mmi(data)
    if data[0] != 0x05 or len(data) < 7:
        return []

    source = data[1]
    application = data[2]
    index = 3
    if data[index] == 0x00:
        index += 1
    elif data[index] == 0x01 and len(data) > index + 1 and data[index + 1] == 0x00:
        index += 2
    else:
        return []

    end = len(data) - 1
    events: list[CbusLevelEvent] = []
    while index < end:
        command = data[index]
        index += 1
        if command in (0x79, 0x01):
            if index >= end:
                break
            group = data[index]
            index += 1
            level = 255 if command == 0x79 else 0
            events.append(CbusLevelEvent(application, group, level, level > 0, source))
            continue
        if command in _RAMP_SECONDS:
            if index + 1 >= end:
                break
            group, level = data[index], data[index + 1]
            index += 2
            events.append(
                CbusLevelEvent(
                    application,
                    group,
                    level,
                    level > 0,
                    source,
                    _RAMP_SECONDS[command],
                )
            )
            continue
        break
    return events


def _parse_mmi(data: bytes) -> list[CbusLevelEvent]:
    expected_following = data[0] - 0xC0
    if expected_following != len(data) - 1 or len(data) < 5:
        return []
    application = data[1]
    start_group = data[2]
    events: list[CbusLevelEvent] = []
    for byte_index, packed in enumerate(data[3:-1]):
        for group_offset in range(4):
            state = (packed >> (group_offset * 2)) & 0x03
            group = start_group + byte_index * 4 + group_offset
            if group > 255 or state == 0:
                continue
            events.append(
                CbusLevelEvent(
                    application=application,
                    group=group,
                    level=0 if state == 2 else None,
                    is_on=True if state == 1 else False if state == 2 else None,
                    from_mmi=True,
                )
            )
    return events


class CbusCniConnection:
    """Maintain one direct TCP connection to a C-Bus CNI."""

    def __init__(
        self,
        host: str,
        port: int,
        monitor_application: int,
        event_callback: Callable[[CbusLevelEvent], None],
        availability_callback: Callable[[bool], None],
    ) -> None:
        self.host = host
        self.port = port
        self.monitor_application = monitor_application
        self._event_callback = event_callback
        self._availability_callback = availability_callback
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._connected = False
        self._write_lock = asyncio.Lock()
        self._confirmations: dict[str, asyncio.Future[bool]] = {}
        self._confirmation_chars = itertools.cycle("jklmnopqrstuvwxyzg")
        self._paused_until = 0.0
        self.last_error: str | None = None

    @property
    def connected(self) -> bool:
        """Return connection state."""
        return self._connected

    def start(self) -> None:
        """Start the reconnecting connection task."""
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(
                self._run(), name=f"C-Bus CNI {self.host}:{self.port}"
            )

    async def stop(self) -> None:
        """Stop and close the connection."""
        self._stopping = True
        if self._task:
            self._task.cancel()
        await self._close()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def pause(self, seconds: float) -> None:
        """Release the CNI for another client for a period."""
        self._paused_until = asyncio.get_running_loop().time() + max(0, seconds)
        await self._close()

    def resume(self) -> None:
        """Resume connection attempts immediately."""
        self._paused_until = 0.0
        if self._task is None or self._task.done():
            self.start()

    async def send_level(
        self,
        application: int,
        group: int,
        level: int,
        transition: float | None = None,
    ) -> None:
        """Send a group level command and await the PCI confirmation."""
        if not self._writer or not self._connected:
            raise ConnectionError("C-Bus CNI is not connected")
        command = encode_lighting_command(application, group, level, transition)
        confirmation = next(self._confirmation_chars)
        future = asyncio.get_running_loop().create_future()
        async with self._write_lock:
            self._confirmations[confirmation] = future
            self._writer.write(command + confirmation.encode("ascii") + b"\r")
            await self._writer.drain()
            try:
                success = await asyncio.wait_for(future, timeout=5)
            finally:
                self._confirmations.pop(confirmation, None)
        if not success:
            raise ConnectionError("The CNI rejected the C-Bus command")

    async def _run(self) -> None:
        retry = 2.0
        while not self._stopping:
            now = asyncio.get_running_loop().time()
            if self._paused_until > now:
                await asyncio.sleep(min(5, self._paused_until - now))
                continue
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), timeout=10
                )
                await self._initialise()
                self.last_error = None
                self._set_connected(True)
                retry = 2.0
                await self._read_loop()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnect loop boundary
                self.last_error = str(err)
                _LOGGER.warning(
                    "C-Bus CNI %s:%s disconnected: %s", self.host, self.port, err
                )
            finally:
                await self._close()
            if not self._stopping:
                await asyncio.sleep(retry)
                retry = min(retry * 2, 60)

    async def _initialise(self) -> None:
        assert self._writer is not None
        # Reset, select the monitoring application, enable Local SAL and MMI monitoring.
        commands = (
            b"~~~\r",
            f"A32100{self.monitor_application:02X}g\r".encode("ascii"),
            b"A3420002h\r",
            b"A3300079i\r",
        )
        for command in commands:
            self._writer.write(command)
            await self._writer.drain()
            await asyncio.sleep(0.08)

    async def _read_loop(self) -> None:
        assert self._reader is not None
        buffer = bytearray()
        while not self._stopping:
            chunk = await self._reader.read(1024)
            if not chunk:
                raise ConnectionError("CNI closed the TCP connection")
            buffer.extend(chunk)
            while b"\r" in buffer:
                raw, _, remainder = buffer.partition(b"\r")
                buffer = bytearray(remainder)
                raw_bytes = bytes(raw).strip(b"\n")
                if raw_bytes:
                    self._handle_line(raw_bytes)

    def _handle_line(self, raw: bytes) -> None:
        text = raw.decode("ascii", errors="ignore").strip()
        match = _CONFIRM_RE.match(text)
        if match:
            code, result = match.groups()
            future = self._confirmations.get(code)
            if future and not future.done():
                future.set_result(result == ".")
            return
        for event in parse_cni_line(raw):
            self._event_callback(event)

    async def _close(self) -> None:
        self._set_connected(False)
        writer, self._writer = self._writer, None
        self._reader = None
        if writer:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
        for future in self._confirmations.values():
            if not future.done():
                future.set_exception(ConnectionError("CNI connection closed"))
        self._confirmations.clear()

    def _set_connected(self, connected: bool) -> None:
        if self._connected == connected:
            return
        self._connected = connected
        self._availability_callback(connected)
