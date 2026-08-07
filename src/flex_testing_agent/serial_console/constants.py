"""Defaults for Flex FTDI serial console access.

See: https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5663293442
"""

from __future__ import annotations

DEFAULT_BAUD: int = 115200
DEFAULT_LOGIN_USER: str = "root"

# Substrings matched (case-insensitive) against device, description, or
# manufacturer when classifying a likely Flex FTDI adapter.
FTDI_MATCH_TOKENS: tuple[str, ...] = (
    "ftdi",
    "usbserial",
    "usb serial",
    "ttl232",
    "ttl-232",
    "ft232",
)

# Prefer call-out devices on macOS (cu.*) over dial-in (tty.*).
MACOS_CU_PREFIX: str = "/dev/cu."
MACOS_TTY_PREFIX: str = "/dev/tty."
