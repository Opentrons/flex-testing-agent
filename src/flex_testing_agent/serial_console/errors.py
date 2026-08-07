"""Errors for FTDI / serial console access."""

from __future__ import annotations


class SerialConsoleError(Exception):
    """Base error for serial console operations."""


class PortNotFoundError(SerialConsoleError):
    """No suitable serial port was found or the given path is missing."""


class LoginError(SerialConsoleError):
    """Failed to reach a usable login or shell prompt on the console."""
