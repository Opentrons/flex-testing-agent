"""``flex-test serial``: FTDI console list / shell / run / CRS remote-access."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from flex_testing_agent.config.settings import Settings, get_settings
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import (
    MutationDeniedError,
    ensure_mutation_allowed,
)
from flex_testing_agent.serial_console import (
    ENABLE_REMOTE_ACCESS_SHELL,
    REMOTE_ACCESS_ALLOW_PATH,
    REMOTE_ACCESS_UNIT,
    PortNotFoundError,
    SerialConsoleError,
    SerialSession,
    enable_remote_access,
    list_serial_devices,
    open_interactive_shell,
    probe_remote_access,
    resolve_serial_port,
    run_command,
)

serial_app = typer.Typer(
    name="serial",
    help=(
        "FTDI USB serial console for Flex (Tabby alternative). "
        "See docs/serial-console.md and docs/crs-testing.md "
        "(remote-access carveout)."
    ),
    no_args_is_help=True,
)
console = Console()


def _resolve_port_and_baud(
    settings: Settings,
    port: str | None,
    baud: int | None,
) -> tuple[str, int]:
    preferred = (port or settings.serial_port or "").strip() or None
    resolved = resolve_serial_port(preferred)
    rate = baud if baud is not None else settings.serial_baud_rate
    return resolved, rate


@serial_app.command("list")
def serial_list() -> None:
    """List serial ports; highlight likely Flex FTDI adapters."""
    devices = list_serial_devices()
    if not devices:
        console.print("[yellow]No serial ports found.[/yellow]")
        raise SystemExit(1)

    table = Table(title="Serial ports")
    table.add_column("Device")
    table.add_column("Likely Flex FTDI")
    table.add_column("Description")
    table.add_column("Manufacturer")
    for device in devices:
        table.add_row(
            device.device,
            "yes" if device.likely_flex_ftdi else "",
            device.description,
            device.manufacturer or "",
        )
    console.print(table)
    likely = [d for d in devices if d.likely_flex_ftdi]
    if likely:
        console.print(f"[dim]Default auto-detect would use:[/dim] {likely[0].device}")
    raise SystemExit(0)


@serial_app.command("shell")
def serial_shell(
    port: str | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Serial device path (default: SERIAL_PORT or auto-detect).",
    ),
    baud: int | None = typer.Option(
        None,
        "--baud",
        "-b",
        help="Baud rate (default: SERIAL_BAUD_RATE / 115200).",
    ),
    do_login: bool = typer.Option(
        True,
        "--login/--no-login",
        help="Auto-login as root before handing off the interactive terminal.",
    ),
) -> None:
    """Interactive Flex serial console (replaces Tabby)."""
    settings = get_settings()
    try:
        resolved, rate = _resolve_port_and_baud(settings, port, baud)
    except PortNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    console.print(f"[dim]Opening {resolved} @ {rate}…[/dim]")
    try:
        open_interactive_shell(resolved, baudrate=rate, login=do_login)
    except SerialConsoleError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    raise SystemExit(0)


@serial_app.command("run")
def serial_run(
    command: str = typer.Argument(..., help="Shell command to run on the Flex."),
    port: str | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Serial device path (default: SERIAL_PORT or auto-detect).",
    ),
    baud: int | None = typer.Option(
        None,
        "--baud",
        "-b",
        help="Baud rate (default: SERIAL_BAUD_RATE / 115200).",
    ),
    do_login: bool = typer.Option(
        True,
        "--login/--no-login",
        help="Auto-login as root before running the command.",
    ),
    timeout: float = typer.Option(
        30.0,
        "--timeout",
        "-t",
        help="Seconds to wait for command output.",
    ),
) -> None:
    """Run one command on the Flex serial console and print output."""
    settings = get_settings()
    try:
        resolved, rate = _resolve_port_and_baud(settings, port, baud)
    except PortNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    console.print(f"[dim]{resolved} @ {rate}: {command}[/dim]")
    try:
        with SerialSession(port=resolved, baudrate=rate) as session:
            output = run_command(
                session,
                command,
                timeout=timeout,
                login=do_login,
            )
    except SerialConsoleError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    console.print(output.rstrip())
    raise SystemExit(0)


@serial_app.command("remote-access-status")
def serial_remote_access_status(
    port: str | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Serial device path (default: SERIAL_PORT or auto-detect).",
    ),
    baud: int | None = typer.Option(
        None,
        "--baud",
        "-b",
        help="Baud rate (default: SERIAL_BAUD_RATE / 115200).",
    ),
    timeout: float = typer.Option(
        30.0,
        "--timeout",
        "-t",
        help="Seconds to wait for command output.",
    ),
) -> None:
    """Probe CRS remote-access carveout (allow file + systemd unit) over serial."""
    settings = get_settings()
    try:
        resolved, rate = _resolve_port_and_baud(settings, port, baud)
    except PortNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    try:
        with SerialSession(port=resolved, baudrate=rate) as session:
            status = probe_remote_access(session, timeout=timeout)
    except SerialConsoleError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    table = Table(title="CRS remote-access carveout", show_header=False)
    table.add_row("Port", resolved)
    table.add_row("Allow path", REMOTE_ACCESS_ALLOW_PATH)
    table.add_row("Unit", REMOTE_ACCESS_UNIT)
    allow = status.allow_file_present
    table.add_row(
        "Allow file",
        "present" if allow is True else "absent" if allow is False else "unknown",
    )
    table.add_row("Unit state", status.unit_active)
    table.add_row(
        "Likely allowed",
        "yes" if status.likely_allowed else "no",
    )
    console.print(table)
    if status.raw.strip():
        console.print(f"[dim]{status.raw.rstrip()}[/dim]")
    raise SystemExit(0 if status.likely_allowed else 2)


@serial_app.command("allow-remote-access")
def serial_allow_remote_access(
    port: str | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Serial device path (default: SERIAL_PORT or auto-detect).",
    ),
    baud: int | None = typer.Option(
        None,
        "--baud",
        "-b",
        help="Baud rate (default: SERIAL_BAUD_RATE / 115200).",
    ),
    timeout: float = typer.Option(
        60.0,
        "--timeout",
        "-t",
        help="Seconds to wait for the remount/touch/restart command.",
    ),
) -> None:
    """QA carveout: remount root RW, touch allow file, restart remote-access unit.

    Required when CRS is on so SSH / Jupyter / devtools work again. Does **not**
    disable CRS. Cleared on the next robot OS update. Needs ALLOW_MUTATIONS=true.
    See docs/crs-testing.md.
    """
    settings = get_settings()
    try:
        ensure_mutation_allowed(
            settings,
            risk_level=RiskLevel.DISRUPTIVE,
            capability_name="serial_allow_remote_access",
        )
    except MutationDeniedError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    try:
        resolved, rate = _resolve_port_and_baud(settings, port, baud)
    except PortNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    console.print(f"[dim]{resolved} @ {rate}[/dim]")
    console.print(f"[yellow]Running:[/yellow] {ENABLE_REMOTE_ACCESS_SHELL}")
    try:
        with SerialSession(port=resolved, baudrate=rate) as session:
            output = enable_remote_access(session, timeout=timeout)
            status = probe_remote_access(session, timeout=min(30.0, timeout))
    except SerialConsoleError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    if output.strip():
        console.print(output.rstrip())
    style = "green" if status.likely_allowed else "yellow"
    console.print(
        f"[{style}]allow_file="
        f"{status.allow_file_present} unit={status.unit_active}[/{style}]"
    )
    raise SystemExit(0 if status.likely_allowed else 2)
