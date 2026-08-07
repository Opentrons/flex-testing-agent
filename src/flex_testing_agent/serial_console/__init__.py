"""FTDI serial console access for Opentrons Flex (KansasFLEX).

Replaces Tabby for the USB/serial cable documented in
https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5663293442
"""

from __future__ import annotations

from flex_testing_agent.serial_console.constants import (
    DEFAULT_BAUD,
    DEFAULT_LOGIN_USER,
)
from flex_testing_agent.serial_console.devices import (
    SerialDevice,
    list_likely_flex_devices,
    list_serial_devices,
    resolve_serial_port,
)
from flex_testing_agent.serial_console.errors import (
    LoginError,
    PortNotFoundError,
    SerialConsoleError,
)
from flex_testing_agent.serial_console.interactive import open_interactive_shell
from flex_testing_agent.serial_console.login import ensure_logged_in, run_command
from flex_testing_agent.serial_console.remote_access import (
    ENABLE_REMOTE_ACCESS_SHELL,
    REMOTE_ACCESS_ALLOW_PATH,
    REMOTE_ACCESS_UNIT,
    RemoteAccessStatus,
    enable_remote_access,
    probe_remote_access,
)
from flex_testing_agent.serial_console.session import (
    SerialSession,
    detect_console_state,
)

__all__ = [
    "DEFAULT_BAUD",
    "DEFAULT_LOGIN_USER",
    "ENABLE_REMOTE_ACCESS_SHELL",
    "REMOTE_ACCESS_ALLOW_PATH",
    "REMOTE_ACCESS_UNIT",
    "LoginError",
    "PortNotFoundError",
    "RemoteAccessStatus",
    "SerialConsoleError",
    "SerialDevice",
    "SerialSession",
    "detect_console_state",
    "enable_remote_access",
    "ensure_logged_in",
    "list_likely_flex_devices",
    "list_serial_devices",
    "open_interactive_shell",
    "probe_remote_access",
    "resolve_serial_port",
    "run_command",
]
