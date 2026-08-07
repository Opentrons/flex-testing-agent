"""``flex-test logs``: list / archive Flex diagnostic logs."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from flex_testing_agent.config.settings import (
    Settings,
    clear_settings_cache,
    get_settings,
)
from flex_testing_agent.logging import configure_logging
from flex_testing_agent.orchestration.discover import (
    RobotDiscoveryError,
    settings_with_resolved_host,
)

logs_app = typer.Typer(
    name="logs",
    help=(
        "Download Flex diagnostic logs (GET /logs/{id}). "
        "See docs/robot-logs.md. Archives land under ARTIFACT_DIRECTORY/logs/."
    ),
    no_args_is_help=True,
)
console = Console()

_DESTINATION_OPTION = typer.Option(
    None,
    "--destination",
    "-d",
    help="Archive directory (default: ARTIFACT_DIRECTORY/logs/<stamp>-<host>/).",
)
_IDENTIFIER_OPTION = typer.Option(
    None,
    "--id",
    help="Log identifier to download (repeatable). Default: discover from /health.",
)


async def _resolve_settings_for_robot(settings: Settings) -> Settings:
    try:
        resolved = await settings_with_resolved_host(settings)
    except RobotDiscoveryError as exc:
        raise ValueError(str(exc)) from exc
    if resolved.robot_host != settings.robot_host:
        console.print(
            f"[yellow]ROBOT_HOST updated via discovery:[/yellow] "
            f"{settings.robot_host or '(unset)'} → {resolved.robot_host}"
        )
    return resolved


@logs_app.command("list")
def logs_list() -> None:
    """List diagnostic log identifiers advertised by ``GET /health``."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        async with FlexRobot(resolved) as robot:
            identifiers = await robot.logs.list_identifiers(
                timeout=resolved.robot_health_timeout_seconds,
                include_defaults=True,
            )

        table = Table(title="Diagnostic log identifiers")
        table.add_column("Identifier")
        table.add_column("Path")
        for ident in identifiers:
            table.add_row(ident, f"/logs/{ident}")
        console.print(table)
        return 0

    raise SystemExit(asyncio.run(_run()))


@logs_app.command("archive")
def logs_archive(
    destination: Path | None = _DESTINATION_OPTION,
    identifier: list[str] | None = _IDENTIFIER_OPTION,
) -> None:
    """Download diagnostic logs into a dated archive with manifest.json."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.capabilities.archive_logs import archive_diagnostic_logs
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        ids = list(identifier) if identifier else None
        async with FlexRobot(resolved) as robot:
            try:
                result = await archive_diagnostic_logs(
                    robot,
                    identifiers=ids,
                    destination=destination,
                )
            except Exception as exc:
                console.print(f"[red]{exc}[/red]")
                return 2

        table = Table(title="Diagnostic log archive", show_header=False)
        table.add_row("Robot host", result.robot_host)
        table.add_row("Robot name", result.robot_name or "—")
        table.add_row("System version", result.system_version or "—")
        table.add_row("API version", result.api_version or "—")
        table.add_row("Archive", str(result.archive_directory))
        table.add_row("Manifest", str(result.manifest_path))
        table.add_row("Downloaded", str(result.downloaded))
        table.add_row("Skipped", str(result.skipped))
        console.print(table)

        files = Table(title="Files")
        files.add_column("Identifier")
        files.add_column("Status")
        files.add_column("Bytes")
        files.add_column("Detail")
        for entry in result.entries:
            if entry.skipped:
                files.add_row(
                    entry.identifier,
                    str(entry.status_code or "—"),
                    "—",
                    entry.detail or "skipped",
                )
            else:
                files.add_row(
                    entry.identifier,
                    str(entry.status_code or "—"),
                    str(entry.byte_size or 0),
                    entry.path or "",
                )
        console.print(files)
        return 0

    raise SystemExit(asyncio.run(_run()))
