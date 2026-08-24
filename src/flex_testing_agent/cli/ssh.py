"""``flex-test ssh``: lab root SSH (CRS-off or CRS-on QA carveout)."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from flex_testing_agent.config.settings import (
    clear_settings_cache,
    get_settings,
)
from flex_testing_agent.lab_ssh.probe import probe_lab_ssh, run_lab_ssh
from flex_testing_agent.logging import configure_logging

ssh_app = typer.Typer(
    name="ssh",
    help=(
        "Lab SSH to the Flex (root). Prefer this over serial when port 22 "
        "works. Not the product HTTP API. See docs/interaction-layers.md."
    ),
    no_args_is_help=True,
)
console = Console()


@ssh_app.command("status")
def ssh_status() -> None:
    """Probe TCP :22 and BatchMode auth (lab key)."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        status = asyncio.run(probe_lab_ssh(settings))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc

    table = Table(title="Lab SSH", show_header=False)
    table.add_row("Host", status.host)
    table.add_row("Port", str(status.port))
    table.add_row("TCP", "open" if status.tcp_reachable else "closed")
    auth = status.authenticated
    table.add_row(
        "Authenticated",
        "yes" if auth is True else "no" if auth is False else "not attempted",
    )
    table.add_row(
        "Identity",
        str(status.identity_path) if status.identity_path else "(none)",
    )
    table.add_row("Detail", status.detail)
    console.print(table)
    if status.authenticated is True:
        raise SystemExit(0)
    raise SystemExit(2)


@ssh_app.command("run")
def ssh_run(
    command: str = typer.Argument(..., help="Remote shell command."),
    timeout: float = typer.Option(
        30.0,
        "--timeout",
        "-t",
        help="Seconds to wait for ssh + command.",
    ),
) -> None:
    """Run one command over lab SSH (BatchMode)."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        settings.require_robot_host()
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc

    completed = run_lab_ssh(settings, command, timeout=timeout)
    if completed is None:
        console.print(
            "[red]SSH did not run (missing ssh binary, key, or timeout). "
            "Try flex-test ssh status, then serial if CRS locked SSH.[/red]"
        )
        raise SystemExit(1)
    if completed.stdout:
        console.print(completed.stdout.rstrip())
    if completed.stderr.strip():
        console.print(f"[dim]{completed.stderr.rstrip()}[/dim]")
    raise SystemExit(completed.returncode)
