"""Interactive serial terminal (Tabby replacement via pyserial miniterm)."""

from __future__ import annotations

from typing import Any

from serial.tools import miniterm

from flex_testing_agent.serial_console.constants import DEFAULT_BAUD
from flex_testing_agent.serial_console.errors import SerialConsoleError
from flex_testing_agent.serial_console.login import ensure_logged_in
from flex_testing_agent.serial_console.session import SerialSession


def open_interactive_shell(
    port: str,
    *,
    baudrate: int = DEFAULT_BAUD,
    login: bool = True,
) -> None:
    """Open an interactive console on ``port`` (blocks until the user exits).

    Exit with Ctrl+] then ``q``. Menu is Ctrl+T.
    """
    session = SerialSession(port=port, baudrate=baudrate, timeout=0.05)
    try:
        if login:
            ensure_logged_in(session)
        ser = session.detach()
        _run_miniterm(ser)
    finally:
        session.close()


def _run_miniterm(ser: Any) -> None:
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
    print(
        f"--- Flex serial console on {port_name} @ {baud} ---\n"
        "Exit: Ctrl+] then q  |  Menu: Ctrl+T\n"
        "Kernel logs may interleave with your typing (expected on Flex).\n"
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
