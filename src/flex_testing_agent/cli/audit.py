"""``flex-test audit``: list / download CRS audit log periods."""

from __future__ import annotations

import asyncio
import contextlib
import json
import zipfile
from io import BytesIO
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

audit_app = typer.Typer(
    name="audit",
    help=(
        "CRS audit log periods (GET /audit/external/logPeriods[/{id}/download]). "
        "See docs/robot-logs.md. Requires CRS on; use ROBOT_USERNAME/PASSWORD."
    ),
    no_args_is_help=True,
)
console = Console()

_DESTINATION_OPTION = typer.Option(
    None,
    "--destination",
    "-d",
    help="Output file (default: ARTIFACT_DIRECTORY/audit/<id>.zip).",
)
_SUMMARIZE_OPTION = typer.Option(
    True,
    "--summarize/--no-summarize",
    help="Print action names found in the downloaded package.",
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


@audit_app.command("list")
def audit_list() -> None:
    """List CRS audit log periods (oldest first)."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.orchestration.crs_auth import optional_access_token
        from flex_testing_agent.orchestration.lock import RobotOperationLock
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        host = resolved.require_robot_host()
        artifact_root = resolved.ensure_artifact_directory()
        try:
            token = await optional_access_token(resolved)
            with RobotOperationLock(host, artifact_root / "locks"):
                async with FlexRobot(resolved, access_token=token) as robot:
                    periods = await robot.audit.list_log_periods()
                    robot.raw_evidence[
                        "audit_log_periods"
                    ] = await robot.audit.list_log_periods_raw()
        except Exception as exc:
            console.print(f"[red]audit list failed: {exc}[/red]")
            return 1

        table = Table(title="Audit log periods")
        table.add_column("ID")
        table.add_column("Started at")
        table.add_column("Ended at")
        for period in periods:
            table.add_row(
                period.id,
                period.started_at or "n/a",
                period.ended_at or "(active)",
            )
        console.print(table)
        console.print(f"[dim]{len(periods)} period(s)[/dim]")
        return 0

    raise SystemExit(asyncio.run(_run()))


@audit_app.command("download")
def audit_download(
    period_id: str = typer.Argument(..., help="Log period id from ``audit list``."),
    destination: Path | None = _DESTINATION_OPTION,
    summarize: bool = _SUMMARIZE_OPTION,
) -> None:
    """Download one audit log period package."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.orchestration.crs_auth import optional_access_token
        from flex_testing_agent.orchestration.lock import RobotOperationLock
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        host = resolved.require_robot_host()
        artifact_root = resolved.ensure_artifact_directory()
        out = destination
        if out is None:
            out_dir = artifact_root / "audit"
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"{period_id}.zip"

        try:
            token = await optional_access_token(resolved)
            with RobotOperationLock(host, artifact_root / "locks"):
                async with FlexRobot(resolved, access_token=token) as robot:
                    downloaded = await robot.audit.download_log_period(period_id)
        except Exception as exc:
            console.print(f"[red]audit download failed: {exc}[/red]")
            return 1

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(downloaded.content)
        console.print(
            f"[green]Wrote[/green] {out} "
            f"({len(downloaded.content)} bytes"
            f"{', ' + downloaded.content_type if downloaded.content_type else ''})"
        )

        if summarize:
            _print_action_summary(downloaded.content)
        return 0

    raise SystemExit(asyncio.run(_run()))


def _print_action_summary(content: bytes) -> None:
    """Best-effort extract of ``action`` fields from a period download."""
    actions: list[str] = []
    try:
        if zipfile.is_zipfile(BytesIO(content)):
            with zipfile.ZipFile(BytesIO(content)) as zf:
                for name in zf.namelist():
                    if not name.endswith((".json", ".log")):
                        continue
                    raw = zf.read(name)
                    actions.extend(_actions_from_bytes(raw))
        else:
            actions.extend(_actions_from_bytes(content))
    except Exception as exc:
        console.print(f"[yellow]Could not summarize package: {exc}[/yellow]")
        return

    if not actions:
        console.print("[dim]No action fields found in package.[/dim]")
        return

    counts: dict[str, int] = {}
    for action in actions:
        counts[action] = counts.get(action, 0) + 1
    table = Table(title="User-action summary")
    table.add_column("Action")
    table.add_column("Count")
    for action, count in sorted(counts.items()):
        table.add_row(action, str(count))
    console.print(table)


def _actions_from_bytes(raw: bytes) -> list[str]:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _collect_actions(parsed)


def _collect_actions(node: object) -> list[str]:
    """Walk export JSON; actions live in nested JSON strings under ``message``."""
    found: list[str] = []
    if isinstance(node, dict):
        action = node.get("action")
        if isinstance(action, str):
            found.append(action)
        for key in ("message", "content"):
            nested = node.get(key)
            if isinstance(nested, str) and nested[:1] in "{[":
                with contextlib.suppress(json.JSONDecodeError):
                    found.extend(_collect_actions(json.loads(nested)))
            elif isinstance(nested, dict | list):
                found.extend(_collect_actions(nested))
        for key, value in node.items():
            if key in {"action", "message", "content"}:
                continue
            found.extend(_collect_actions(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_collect_actions(item))
    return found
