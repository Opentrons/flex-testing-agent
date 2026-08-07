"""``flex-test serial``: FTDI console list / shell / run / CRS remote-access."""

from __future__ import annotations

from pathlib import Path

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
    partition_console_text,
    probe_remote_access,
    resolve_serial_port,
    run_command_result,
    watch_console,
)
from flex_testing_agent.serial_console.transcript import (
    record_transcript,
    resolve_transcript_paths,
    write_operation_header,
)

serial_app = typer.Typer(
    name="serial",
    help=(
        "FTDI USB serial console for Flex (Tabby alternative). "
        "Transcripts default to ARTIFACT_DIRECTORY/serial/. "
        "See docs/serial-console.md."
    ),
    no_args_is_help=True,
)
console = Console()

_LOG_FILE_OPTION = typer.Option(
    None,
    "--log",
    help=(
        "Per-run transcript path. Default: "
        "ARTIFACT_DIRECTORY/serial/<UTC>-<kind>.log when --save-log."
    ),
)

_SAVE_LOG_OPTION = typer.Option(
    True,
    "--save-log/--no-save-log",
    help=(
        "Save transcripts under ARTIFACT_DIRECTORY/serial/ "
        "(per-run file + daily YYYYMMDD-console.log). Default: on."
    ),
)


def _resolve_port_and_baud(
    settings: Settings,
    port: str | None,
    baud: int | None,
) -> tuple[str, int]:
    preferred = (port or settings.serial_port or "").strip() or None
    resolved = resolve_serial_port(preferred)
    rate = baud if baud is not None else settings.serial_baud_rate
    return resolved, rate


def _begin_transcripts(
    settings: Settings,
    *,
    kind: str,
    port: str,
    baudrate: int,
    log_file: Path | None,
    save_log: bool,
    detail: str = "",
) -> tuple[Path | None, Path | None]:
    """Resolve log paths, write headers, and print destinations."""
    per_run, daily = resolve_transcript_paths(
        settings.ensure_artifact_directory(),
        kind=kind,
        log_file=log_file,
        save_log=save_log,
    )
    for path in (per_run, daily):
        if path is not None:
            write_operation_header(
                path,
                kind=kind,
                port=port,
                baudrate=baudrate,
                detail=detail,
            )
    if per_run is not None:
        console.print(f"[dim]transcript:[/dim] {per_run}")
    if daily is not None:
        console.print(f"[dim]daily log:[/dim] {daily}")
    return per_run, daily


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
    log_file: Path | None = _LOG_FILE_OPTION,
    save_log: bool = _SAVE_LOG_OPTION,
) -> None:
    """Interactive Flex serial console (replaces Tabby). Saves a transcript."""
    settings = get_settings()
    try:
        resolved, rate = _resolve_port_and_baud(settings, port, baud)
    except PortNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    per_run, daily = _begin_transcripts(
        settings,
        kind="shell",
        port=resolved,
        baudrate=rate,
        log_file=log_file,
        save_log=save_log,
    )
    console.print(f"[dim]Opening {resolved} @ {rate}…[/dim]")
    try:
        open_interactive_shell(
            resolved,
            baudrate=rate,
            login=do_login,
            log_per_run=per_run,
            log_daily=daily,
        )
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
    include_kernel: bool = typer.Option(
        False,
        "--include-kernel/--no-include-kernel",
        help=(
            "Also print kernel printk lines captured during the command "
            "(still always saved in the transcript when --save-log)."
        ),
    ),
    log_file: Path | None = _LOG_FILE_OPTION,
    save_log: bool = _SAVE_LOG_OPTION,
) -> None:
    """Run one command; save full transcript (command + kernel) by default."""
    settings = get_settings()
    try:
        resolved, rate = _resolve_port_and_baud(settings, port, baud)
    except PortNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    per_run, daily = _begin_transcripts(
        settings,
        kind="run",
        port=resolved,
        baudrate=rate,
        log_file=log_file,
        save_log=save_log,
        detail=f"command={command!r}",
    )
    console.print(f"[dim]{resolved} @ {rate}: {command}[/dim]")
    try:
        with SerialSession(port=resolved, baudrate=rate) as session:
            result = run_command_result(
                session,
                command,
                timeout=timeout,
                login=do_login,
            )
    except SerialConsoleError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    record_transcript(result.raw + "\n", per_run=per_run, daily=daily)

    if result.output.strip():
        console.print(result.output.rstrip())
    if include_kernel and result.kernel_lines:
        console.print("[magenta]--- kernel printk ---[/magenta]")
        console.print("\n".join(result.kernel_lines))
    elif result.kernel_lines and (per_run is not None or daily is not None):
        console.print(
            f"[dim]({len(result.kernel_lines)} kernel line(s) in transcript; "
            "pass --include-kernel to print)[/dim]"
        )
    raise SystemExit(0)


@serial_app.command("watch")
def serial_watch(
    seconds: float = typer.Option(
        30.0,
        "--seconds",
        "-s",
        help="How long to listen (captures kernel + any console traffic).",
    ),
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
    log_file: Path | None = _LOG_FILE_OPTION,
    save_log: bool = _SAVE_LOG_OPTION,
    print_kernel_only: bool = typer.Option(
        False,
        "--kernel-only/--all",
        help="Print only lines that look like kernel printk / oops / boot.",
    ),
) -> None:
    """Listen on the serial console; save kernel/boot transcript by default."""
    settings = get_settings()
    try:
        resolved, rate = _resolve_port_and_baud(settings, port, baud)
    except PortNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    per_run, daily = _begin_transcripts(
        settings,
        kind="watch",
        port=resolved,
        baudrate=rate,
        log_file=log_file,
        save_log=save_log,
        detail=f"seconds={seconds}",
    )
    console.print(
        f"[dim]Watching {resolved} @ {rate} for {seconds:.0f}s "
        "(kernel printk expected; Ctrl+C to stop early)…[/dim]"
    )
    try:
        with SerialSession(port=resolved, baudrate=rate, timeout=0.05) as session:
            try:
                text = watch_console(session, seconds=seconds)
            except KeyboardInterrupt:
                text = session.drain(0.2)
                text = (text or "") + "\n"
    except SerialConsoleError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    parts = partition_console_text(text)
    record_transcript(parts.raw + "\n", per_run=per_run, daily=daily)
    display = parts.kernel_text if print_kernel_only else parts.raw
    if display.strip():
        console.print(display.rstrip())
    console.print(
        f"[dim]captured {len(parts.raw)} chars; "
        f"kernel_lines={len(parts.kernel_lines)} "
        f"other_lines={len(parts.other_lines)}[/dim]"
    )
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
    log_file: Path | None = _LOG_FILE_OPTION,
    save_log: bool = _SAVE_LOG_OPTION,
) -> None:
    """Probe CRS remote-access carveout; save transcript by default."""
    settings = get_settings()
    try:
        resolved, rate = _resolve_port_and_baud(settings, port, baud)
    except PortNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    per_run, daily = _begin_transcripts(
        settings,
        kind="remote-access-status",
        port=resolved,
        baudrate=rate,
        log_file=log_file,
        save_log=save_log,
    )
    try:
        with SerialSession(port=resolved, baudrate=rate) as session:
            status = probe_remote_access(session, timeout=timeout)
    except SerialConsoleError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    record_transcript(status.raw + "\n", per_run=per_run, daily=daily)

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
    log_file: Path | None = _LOG_FILE_OPTION,
    save_log: bool = _SAVE_LOG_OPTION,
) -> None:
    """QA carveout: remount/touch/restart remote-access; save transcript.

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

    per_run, daily = _begin_transcripts(
        settings,
        kind="allow-remote-access",
        port=resolved,
        baudrate=rate,
        log_file=log_file,
        save_log=save_log,
        detail=ENABLE_REMOTE_ACCESS_SHELL,
    )
    console.print(f"[dim]{resolved} @ {rate}[/dim]")
    console.print(f"[yellow]Running:[/yellow] {ENABLE_REMOTE_ACCESS_SHELL}")
    try:
        with SerialSession(port=resolved, baudrate=rate) as session:
            output = enable_remote_access(session, timeout=timeout)
            status = probe_remote_access(session, timeout=min(30.0, timeout))
    except SerialConsoleError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    blob = f"{output}\n--- status ---\n{status.raw}\n"
    record_transcript(blob, per_run=per_run, daily=daily)

    if output.strip():
        console.print(output.rstrip())
    style = "green" if status.likely_allowed else "yellow"
    console.print(
        f"[{style}]allow_file="
        f"{status.allow_file_present} unit={status.unit_active}[/{style}]"
    )
    raise SystemExit(0 if status.likely_allowed else 2)
