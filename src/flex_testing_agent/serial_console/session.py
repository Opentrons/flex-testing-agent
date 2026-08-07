"""Low-level serial port session for the Flex console."""

from __future__ import annotations

import re
import time
from types import TracebackType
from typing import Protocol

import serial

from flex_testing_agent.serial_console.constants import DEFAULT_BAUD
from flex_testing_agent.serial_console.errors import SerialConsoleError

# Typical Flex login / shell markers (hostname varies; prompt is usually root@…:~#).
_LOGIN_RE = re.compile(r"login:\s*$", re.MULTILINE | re.IGNORECASE)
_PASSWORD_RE = re.compile(r"password:\s*$", re.MULTILINE | re.IGNORECASE)
_SHELL_RE = re.compile(r"[#\$]\s*$", re.MULTILINE)


class SerialTransport(Protocol):
    """Minimal serial transport for testing and production."""

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...

    @property
    def in_waiting(self) -> int: ...


class SerialSession:
    """Context-managed serial session with line helpers."""

    def __init__(
        self,
        port: str,
        *,
        baudrate: int = DEFAULT_BAUD,
        timeout: float = 0.2,
        transport: SerialTransport | None = None,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._owned = transport is None
        self._ser: SerialTransport
        if transport is not None:
            self._ser = transport
        else:
            try:
                self._ser = serial.Serial(
                    port=port,
                    baudrate=baudrate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=timeout,
                    write_timeout=timeout,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                )
            except serial.SerialException as exc:
                hint = ""
                err = str(exc).lower()
                if "busy" in err or "resource busy" in err or "errno 16" in err:
                    hint = (
                        " Another program may have the port open "
                        "(close Tabby or other serial terminals)."
                    )
                raise SerialConsoleError(
                    f"Failed to open serial port {port!r}: {exc}.{hint}"
                ) from exc

    def __enter__(self) -> SerialSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def raw(self) -> SerialTransport:
        """Underlying transport (for interactive handoff)."""
        return self._ser

    def close(self) -> None:
        """Close the port when this session owns it."""
        if self._owned:
            self._ser.close()
            self._owned = False

    def detach(self) -> SerialTransport:
        """Release ownership of the underlying transport without closing it.

        Used to hand the open port to an interactive terminal driver.
        """
        self._owned = False
        return self._ser

    def write_bytes(self, data: bytes) -> None:
        """Write raw bytes and flush."""
        self._ser.write(data)
        self._ser.flush()

    def write_line(self, line: str, *, newline: str = "\n") -> None:
        """Write a text line (UTF-8) plus newline."""
        self.write_bytes((line + newline).encode("utf-8", errors="replace"))

    def read_available(self) -> bytes:
        """Read whatever is currently buffered (plus one timed read)."""
        chunks: list[bytes] = []
        waiting = self._ser.in_waiting
        if waiting:
            chunks.append(self._ser.read(waiting))
        more = self._ser.read(4096)
        if more:
            chunks.append(more)
        return b"".join(chunks)

    def read_until(
        self,
        deadline: float,
        *,
        patterns: tuple[re.Pattern[str], ...] | None = None,
        idle_settle: float = 0.15,
    ) -> str:
        """Read decoded text until a pattern matches or ``deadline`` (monotonic).

        Also returns early after ``idle_settle`` seconds with no new data once
        some bytes have been seen (useful after probing with Enter).
        """
        buf = bytearray()
        last_data = time.monotonic()
        saw_data = False
        while time.monotonic() < deadline:
            chunk = self.read_available()
            if chunk:
                buf.extend(chunk)
                last_data = time.monotonic()
                saw_data = True
                text = buf.decode("utf-8", errors="replace")
                if patterns:
                    for pattern in patterns:
                        if pattern.search(text):
                            return text
            elif saw_data and (time.monotonic() - last_data) >= idle_settle:
                break
            else:
                time.sleep(0.02)
        return buf.decode("utf-8", errors="replace")

    def drain(self, seconds: float = 0.3) -> str:
        """Read and discard/return pending output for a short window."""
        return self.read_until(time.monotonic() + seconds, idle_settle=0.05)


def detect_console_state(text: str) -> str:
    """Classify console text as login, password, shell, or unknown."""
    stripped = text.rstrip()
    if _PASSWORD_RE.search(stripped):
        return "password"
    if _LOGIN_RE.search(stripped):
        return "login"
    if _SHELL_RE.search(stripped):
        return "shell"
    # Also accept common Flex shell banners without trailing whitespace quirks.
    if re.search(r"root@\S+:.*[#\$]", stripped):
        return "shell"
    return "unknown"
