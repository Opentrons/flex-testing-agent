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
from flex_testing_agent.serial_console.kernel_log import (
    PartitionedConsole,
    is_kernel_log_line,
    partition_console_text,
)
from flex_testing_agent.serial_console.login import (
    CommandResult,
    ensure_logged_in,
    probe_console_state,
    run_command,
    run_command_result,
    watch_console,
)
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
from flex_testing_agent.serial_console.transcript import (
    TeeSerial,
    append_transcript,
    daily_console_log_path,
    default_serial_log_path,
    record_transcript,
    resolve_transcript_paths,
    serial_log_directory,
    write_operation_header,
)

__all__ = [
    "DEFAULT_BAUD",
    "DEFAULT_LOGIN_USER",
    "ENABLE_REMOTE_ACCESS_SHELL",
    "REMOTE_ACCESS_ALLOW_PATH",
    "REMOTE_ACCESS_UNIT",
    "CommandResult",
    "LoginError",
    "PartitionedConsole",
    "PortNotFoundError",
    "RemoteAccessStatus",
    "SerialConsoleError",
    "SerialDevice",
    "SerialSession",
    "TeeSerial",
    "append_transcript",
    "daily_console_log_path",
    "default_serial_log_path",
    "detect_console_state",
    "enable_remote_access",
    "ensure_logged_in",
    "is_kernel_log_line",
    "list_likely_flex_devices",
    "list_serial_devices",
    "open_interactive_shell",
    "partition_console_text",
    "probe_console_state",
    "probe_remote_access",
    "record_transcript",
    "resolve_serial_port",
    "resolve_transcript_paths",
    "run_command",
    "run_command_result",
    "serial_log_directory",
    "watch_console",
    "write_operation_header",
]
