"""Unit tests for FTDI serial console device discovery and session helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from flex_testing_agent.serial_console.devices import (
    list_serial_devices,
    resolve_serial_port,
)
from flex_testing_agent.serial_console.errors import LoginError, PortNotFoundError
from flex_testing_agent.serial_console.login import ensure_logged_in, run_command
from flex_testing_agent.serial_console.session import (
    SerialSession,
    detect_console_state,
)


@dataclass
class FakePort:
    device: str
    description: str = ""
    manufacturer: str | None = None
    hwid: str = ""
    name: str = ""
    product: str | None = None


class FakeTransport:
    """In-memory serial transport for login/run tests."""

    def __init__(self, script: list[tuple[str, bytes]]) -> None:
        """``script``: list of (when_seen_in_written, response_bytes)."""
        self._script = script
        self._written = bytearray()
        self._rx = bytearray()
        self.closed = False

    def write(self, data: bytes) -> int:
        self._written.extend(data)
        written_text = self._written.decode("utf-8", errors="replace")
        remaining: list[tuple[str, bytes]] = []
        for trigger, response in self._script:
            if trigger in written_text and response:
                self._rx.extend(response)
                remaining.append((trigger, b""))  # fire once
            else:
                remaining.append((trigger, response))
        self._script = remaining
        return len(data)

    def flush(self) -> None:
        return None

    def read(self, size: int = 1) -> bytes:
        if not self._rx:
            return b""
        out = bytes(self._rx[:size])
        del self._rx[:size]
        return out

    @property
    def in_waiting(self) -> int:
        return len(self._rx)

    def close(self) -> None:
        self.closed = True

    def push(self, data: bytes) -> None:
        self._rx.extend(data)


def test_list_prefers_cu_over_tty_sibling() -> None:
    ports = [
        FakePort("/dev/tty.usbserial-ABC", description="FTDI USB Serial"),
        FakePort("/dev/cu.usbserial-ABC", description="FTDI USB Serial"),
        FakePort("/dev/cu.Bluetooth-Incoming-Port", description="Bluetooth"),
    ]
    devices = list_serial_devices(ports=ports)
    paths = [d.device for d in devices]
    assert "/dev/cu.usbserial-ABC" in paths
    assert "/dev/tty.usbserial-ABC" not in paths
    assert "/dev/cu.Bluetooth-Incoming-Port" in paths


def test_likely_flex_ftdi_heuristic() -> None:
    ports = [
        FakePort(
            "/dev/cu.usbserial-ABAKGEZI",
            description="USB Serial",
            manufacturer="FTDI",
        ),
        FakePort("/dev/cu.Bluetooth-Incoming-Port", description="Bluetooth"),
    ]
    devices = list_serial_devices(ports=ports)
    by_path = {d.device: d for d in devices}
    assert by_path["/dev/cu.usbserial-ABAKGEZI"].likely_flex_ftdi is True
    assert by_path["/dev/cu.Bluetooth-Incoming-Port"].likely_flex_ftdi is False


def test_resolve_prefers_configured_then_ftdi() -> None:
    ports = [
        FakePort("/dev/cu.usbserial-1", description="FTDI"),
        FakePort("/dev/cu.usbserial-2", description="FTDI"),
    ]
    assert resolve_serial_port(None, ports=ports) == "/dev/cu.usbserial-1"
    assert (
        resolve_serial_port("/dev/cu.usbserial-2", ports=ports) == "/dev/cu.usbserial-2"
    )


def test_resolve_missing_preferred_raises() -> None:
    ports = [FakePort("/dev/cu.usbserial-1", description="FTDI")]
    with pytest.raises(PortNotFoundError):
        resolve_serial_port("/dev/cu.missing", ports=ports)


def test_resolve_no_ftdi_raises() -> None:
    ports = [FakePort("/dev/cu.Bluetooth-Incoming-Port", description="Bluetooth")]
    with pytest.raises(PortNotFoundError):
        resolve_serial_port(None, ports=ports)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("platypus login: ", "login"),
        ("KansasFLEX login:\n", "login"),
        ("Password: ", "password"),
        ("root@KansasFLEX:~# ", "shell"),
        ("root@FLXA:~$ ", "shell"),
        ("random kernel noise", "unknown"),
    ],
)
def test_detect_console_state(text: str, expected: str) -> None:
    assert detect_console_state(text) == expected


def test_ensure_logged_in_from_login_prompt() -> None:
    transport = FakeTransport(
        [
            (
                "\n",
                b"\r\nKansasFLEX login: ",
            ),
            (
                "root\n",
                b"root\r\nroot@KansasFLEX:~# ",
            ),
        ]
    )
    # Seed first probe response before any write matching is tricky; push
    # initial banner so first read sees login after write of \r/\n.
    session = SerialSession(
        port="fake",
        transport=transport,
        timeout=0.05,
    )
    # Preload login prompt for first probe after Enter.
    transport.push(b"KansasFLEX login: ")
    text = ensure_logged_in(session, timeout=2.0)
    assert "root@KansasFLEX" in text or detect_console_state(text) == "shell"


def test_ensure_logged_in_already_shell() -> None:
    transport = FakeTransport([])
    transport.push(b"root@KansasFLEX:~# ")
    session = SerialSession(port="fake", transport=transport, timeout=0.05)
    text = ensure_logged_in(session, timeout=2.0)
    assert detect_console_state(text) == "shell"


def test_ensure_logged_in_timeout() -> None:
    transport = FakeTransport([])
    session = SerialSession(port="fake", transport=transport, timeout=0.01)
    with pytest.raises(LoginError):
        ensure_logged_in(session, timeout=0.2)


def test_run_command_extracts_marker_body() -> None:
    transport = FakeTransport([])
    session = SerialSession(port="fake", transport=transport, timeout=0.05)

    written: dict[str, Any] = {"cmd": ""}

    original_write = transport.write

    def write_and_respond(data: bytes) -> int:
        n = original_write(data)
        text = data.decode("utf-8", errors="replace")
        if "echo __FTA_CMD_" in text and "_END" in text:
            # Parse marker from the command line we just wrote.
            # Format: echo MARKER; cmd; echo MARKER_END
            parts = text.split(";", 1)[0]
            marker = parts.replace("echo ", "").strip()
            transport.push(
                f"{marker}\r\nactive\r\n{marker}_END\r\nroot@host:~# ".encode()
            )
            written["cmd"] = text
        elif text in {"\r", "\n", "\r\n"}:
            transport.push(b"root@host:~# ")
        return n

    transport.write = write_and_respond  # type: ignore[method-assign]

    out = run_command(
        session,
        "systemctl is-active opentrons-robot-server",
        timeout=2.0,
    )
    assert "active" in out


def test_enable_remote_access_shell_uses_merged_paths() -> None:
    from flex_testing_agent.serial_console.remote_access import (
        ENABLE_REMOTE_ACCESS_SHELL,
        REMOTE_ACCESS_ALLOW_PATH,
        REMOTE_ACCESS_UNIT,
    )

    assert REMOTE_ACCESS_ALLOW_PATH == "/etc/opentrons-allow-remote-access"
    assert REMOTE_ACCESS_UNIT == "opentrons-remote-access-allowed"
    assert "mount -o remount,rw /" in ENABLE_REMOTE_ACCESS_SHELL
    assert REMOTE_ACCESS_ALLOW_PATH in ENABLE_REMOTE_ACCESS_SHELL
    assert REMOTE_ACCESS_UNIT in ENABLE_REMOTE_ACCESS_SHELL
    # Reject draft names from early Slack discussion.
    assert ".allow-remote-access" not in ENABLE_REMOTE_ACCESS_SHELL
    assert "jupyter-notebook" not in ENABLE_REMOTE_ACCESS_SHELL


@pytest.mark.parametrize(
    ("raw", "allow", "unit", "likely"),
    [
        ("ALLOW_FILE=yes\nactive\n", True, "active", True),
        ("ALLOW_FILE=no\ninactive\n", False, "inactive", False),
        ("ALLOW_FILE=yes\nunit-missing\n", True, "unit-missing", False),
        ("noise\n", None, "unknown", False),
    ],
)
def test_parse_remote_access_status(
    raw: str,
    allow: bool | None,
    unit: str,
    likely: bool,
) -> None:
    from flex_testing_agent.serial_console.remote_access import (
        parse_remote_access_status,
    )

    status = parse_remote_access_status(raw)
    assert status.allow_file_present is allow
    assert status.unit_active == unit
    assert status.likely_allowed is likely
