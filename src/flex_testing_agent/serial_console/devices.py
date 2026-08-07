"""Enumerate and resolve FTDI / usbserial console devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from serial.tools import list_ports
from serial.tools.list_ports_common import ListPortInfo

from flex_testing_agent.serial_console.constants import (
    FTDI_MATCH_TOKENS,
    MACOS_CU_PREFIX,
    MACOS_TTY_PREFIX,
)
from flex_testing_agent.serial_console.errors import PortNotFoundError


@dataclass(frozen=True, slots=True)
class SerialDevice:
    """A serial port that may be a Flex FTDI console adapter."""

    device: str
    description: str
    manufacturer: str | None
    hwid: str
    likely_flex_ftdi: bool

    @property
    def summary(self) -> str:
        """One-line operator-facing description."""
        mfr = self.manufacturer or "unknown"
        tag = "likely-flex-ftdi" if self.likely_flex_ftdi else "other"
        return f"{self.device}  [{tag}]  {self.description}  ({mfr})"


def _haystack(info: ListPortInfo) -> str:
    parts = [
        info.device or "",
        info.description or "",
        info.manufacturer or "",
        info.hwid or "",
        info.name or "",
        info.product or "",
    ]
    return " ".join(parts).lower()


def is_likely_flex_ftdi(info: ListPortInfo | SerialDevice) -> bool:
    """Return True when the port looks like an FTDI / usbserial Flex cable."""
    if isinstance(info, SerialDevice):
        text = " ".join(
            [
                info.device,
                info.description,
                info.manufacturer or "",
                info.hwid,
            ]
        ).lower()
    else:
        text = _haystack(info)
    return any(token in text for token in FTDI_MATCH_TOKENS)


def _from_list_port(info: ListPortInfo) -> SerialDevice:
    return SerialDevice(
        device=info.device,
        description=info.description or "",
        manufacturer=info.manufacturer,
        hwid=info.hwid or "",
        likely_flex_ftdi=is_likely_flex_ftdi(info),
    )


def _prefer_cu_over_tty(devices: list[SerialDevice]) -> list[SerialDevice]:
    """Drop macOS tty.* entries when a matching cu.* sibling exists."""
    cu_devices = {d.device for d in devices if d.device.startswith(MACOS_CU_PREFIX)}
    filtered: list[SerialDevice] = []
    for device in devices:
        path = device.device
        if path.startswith(MACOS_TTY_PREFIX):
            sibling = MACOS_CU_PREFIX + path.removeprefix(MACOS_TTY_PREFIX)
            if sibling in cu_devices:
                continue
        filtered.append(device)
    return filtered


def list_serial_devices(
    *,
    ports: list[Any] | None = None,
) -> list[SerialDevice]:
    """Return serial ports, preferring cu.* over tty.* on macOS.

    ``ports`` is injectable for tests (objects with ListPortInfo fields).
    """
    raw = ports if ports is not None else list(list_ports.comports())
    devices = [_from_list_port(info) for info in raw]
    return _prefer_cu_over_tty(devices)


def list_likely_flex_devices(
    *,
    ports: list[Any] | None = None,
) -> list[SerialDevice]:
    """Return only ports that match Flex FTDI heuristics."""
    return [d for d in list_serial_devices(ports=ports) if d.likely_flex_ftdi]


def resolve_serial_port(
    preferred: str | None = None,
    *,
    ports: list[Any] | None = None,
) -> str:
    """Resolve a serial device path.

    Order:
    1. Explicit ``preferred`` (must exist among enumerated ports, or be used as-is
       when it looks like an absolute path and ports injection is unused).
    2. First likely Flex FTDI device.
    3. Error if nothing matches.
    """
    devices = list_serial_devices(ports=ports)
    by_device = {d.device: d for d in devices}

    if preferred and preferred.strip():
        path = preferred.strip()
        if path in by_device:
            return path
        # Allow an explicit path even if list_ports missed it (hotplug race).
        if ports is None:
            return path
        raise PortNotFoundError(
            f"SERIAL_PORT {path!r} not found among: "
            f"{[d.device for d in devices] or '(none)'}"
        )

    likely = [d for d in devices if d.likely_flex_ftdi]
    if likely:
        return likely[0].device

    raise PortNotFoundError(
        "No FTDI / usbserial console device found. "
        "Plug in the Flex FTDI cable or set SERIAL_PORT. "
        f"Seen: {[d.device for d in devices] or '(none)'}"
    )
