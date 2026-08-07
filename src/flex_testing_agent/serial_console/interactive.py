"""Interactive serial terminal (Tabby replacement via pyserial miniterm)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from serial.tools import miniterm

from flex_testing_agent.serial_console.constants import DEFAULT_BAUD
from flex_testing_agent.serial_console.errors import SerialConsoleError
from flex_testing_agent.serial_console.login import ensure_logged_in
from flex_testing_agent.serial_console.session import SerialSession
from flex_testing_agent.serial_console.transcript import TeeSerial


def open_interactive_shell(
    port: str,
    *,
    baudrate: int = DEFAULT_BAUD,
    login: bool = True,
    log_per_run: Path | None = None,
    log_daily: Path | None = None,
) -> None:
    """Open an interactive console on ``port`` (blocks until the user exits).

    Exit with Ctrl+] then ``q``. Menu is Ctrl+T. When log paths are set, all
    RX/TX (including kernel printk) is teed into those transcripts.
    """
    session = SerialSession(port=port, baudrate=baudrate, timeout=0.05)
    try:
        if login:
            ensure_logged_in(session)
        ser: Any = session.detach()
        if log_per_run is not None or log_daily is not None:
            ser = TeeSerial(ser, per_run=log_per_run, daily=log_daily)
        _run_miniterm(ser, log_per_run=log_per_run)
    finally:
        session.close()


def _run_miniterm(ser: Any, *, log_per_run: Path | None = None) -> None:
    """Attach pyserial miniterm to an open serial port."""
    try:
        term = miniterm.Miniterm(ser, echo=False)
    except Exception as exc:  # pragma: no cover - construction failures
        raise SerialConsoleError(
            f"Failed to start interactive terminal: {exc}"
        ) from exc

    term.exit_character = chr(0x1D)  # Ctrl+]
    term.menu_character = chr(0x14)  # Ctrl+T

    port_name = getattr(ser, "port", "?")
    baud = getattr(ser, "baudrate", "?")
    log_hint = (
        f"Transcript: {log_per_run}\n"
        if log_per_run is not None
        else "Transcript saving disabled (--no-save-log).\n"
    )
    print(
        f"--- Flex serial console on {port_name} @ {baud} ---\n"
        "Exit: Ctrl+] then q  |  Menu: Ctrl+T\n"
        "Kernel printk will interleave with typing (Flex console = kernel\n"
        "debug device). That is expected and useful for boot/driver debug.\n"
        f"{log_hint}"
        "See docs/serial-console.md and the Confluence FTDI guide.\n"
        "----------------------------------------------------------------",
        flush=True,
    )
    term.start()
    try:
        term.join(True)
    except KeyboardInterrupt:
        pass
    finally:
        term.join()
        term.close()
