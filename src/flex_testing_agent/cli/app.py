"""``flex-test app``: attach to the Opentrons desktop app over CDP."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from flex_testing_agent.app_cdp.connect import (
    DEFAULT_CDP_PORT,
    attach_to_app,
    cdp_is_ready,
    launch_and_attach,
    resolve_cdp_endpoint,
)
from flex_testing_agent.app_cdp.discovery import get_opentrons_app_path
from flex_testing_agent.app_cdp.scenarios.compliance_common import PasswordExpiredError
from flex_testing_agent.app_cdp.scenarios.compliance_settings import (
    format_mismatches,
    run_compliance_settings_scenario,
)
from flex_testing_agent.app_cdp.scenarios.compliance_users import (
    run_compliance_users_scenario,
)
from flex_testing_agent.config.settings import clear_settings_cache, get_settings
from flex_testing_agent.logging import configure_logging

app_app = typer.Typer(
    name="app",
    help=(
        "Attach to the installed Opentrons desktop app over Chrome DevTools "
        "Protocol (Playwright). Requires: uv sync --extra app. "
        "See AppE2E open_app.py for the upstream reference."
    ),
    no_args_is_help=True,
)
console = Console()

_LOG_FILE_OPTION = typer.Option(
    None,
    "--log-file",
    help="Redirect app stdout/stderr to this file.",
)


@app_app.command("status")
def app_status(
    port: int = typer.Option(
        DEFAULT_CDP_PORT,
        "--port",
        "-p",
        help="CDP port (default 9222; override with CDP_PORT).",
    ),
    host: str = typer.Option(
        "",
        "--host",
        help="CDP host (default 127.0.0.1; override with CDP_HOST).",
    ),
) -> None:
    """Report installed app path and whether CDP is reachable."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    cdp_host, cdp_port = resolve_cdp_endpoint(
        host=host or None,
        port=port,
    )
    table = Table(title="Opentrons desktop app (CDP)", show_header=False)
    try:
        app_path = get_opentrons_app_path()
        table.add_row("Executable", str(app_path))
    except (FileNotFoundError, OSError) as exc:
        table.add_row("Executable", f"(not found: {exc})")
    table.add_row("CDP endpoint", f"http://{cdp_host}:{cdp_port}")
    ready = cdp_is_ready(cdp_port, host=cdp_host)
    table.add_row("CDP ready", "yes" if ready else "no")
    console.print(table)
    raise SystemExit(0 if ready else 2)


@app_app.command("launch")
def app_launch(
    port: int = typer.Option(DEFAULT_CDP_PORT, "--port", "-p"),
    attach_only: bool = typer.Option(
        False,
        "--attach-only",
        help="Fail if CDP is not already up (do not launch the app).",
    ),
    log_file: Path | None = _LOG_FILE_OPTION,
) -> None:
    """Launch the app with CDP (or attach if port is already in use)."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    try:
        if attach_only:
            connection = attach_to_app(debug_port=port)
            mode = "attach"
        else:
            connection = launch_and_attach(
                debug_port=port,
                quiet=log_file is None,
                log_file=log_file,
            )
            mode = "attach" if connection.process is None else "launch"
    except (RuntimeError, TimeoutError, FileNotFoundError, OSError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc

    page = connection.page
    console.print(f"[green]Connected ({mode}):[/green] '{page.title()}' ({page.url})")
    connection.close()
    raise SystemExit(0)


@app_app.command("connect")
def app_connect(
    port: int = typer.Option(DEFAULT_CDP_PORT, "--port", "-p"),
    host: str = typer.Option("", "--host"),
) -> None:
    """Attach Playwright to a running app with CDP enabled."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    try:
        connection = attach_to_app(
            debug_port=port,
            host=host or None,
        )
    except (RuntimeError, TimeoutError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc

    page = connection.page
    console.print(f"[green]Connected:[/green] '{page.title()}' ({page.url})")
    connection.close()
    raise SystemExit(0)


@app_app.command("compliance-users")
def app_compliance_users(
    port: int = typer.Option(DEFAULT_CDP_PORT, "--port", "-p"),
    attach_only: bool = typer.Option(
        False,
        "--attach-only",
        help="Attach to an app already running with CDP (do not launch).",
    ),
    allow_extra_users: bool = typer.Option(
        False,
        "--allow-extra-users",
        help="Do not fail when the UI lists users beyond crs_users.yaml fixtures.",
    ),
    log_file: Path | None = _LOG_FILE_OPTION,
) -> None:
    """Log in as admin, open Compliance Ready user management, validate users."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    connection = None
    try:
        if attach_only:
            connection = attach_to_app(debug_port=port)
        else:
            connection = launch_and_attach(
                debug_port=port,
                quiet=log_file is None,
                log_file=log_file,
            )
        result = run_compliance_users_scenario(
            connection.page,
            settings=settings,
            allow_extra_users=allow_extra_users,
        )
    except PasswordExpiredError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise SystemExit(3) from exc
    except (RuntimeError, TimeoutError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc
    finally:
        if connection is not None:
            connection.close()

    table = Table(title="Compliance user management (App)", show_header=False)
    table.add_row("Robot", result.robot_name)
    table.add_row("Admin", result.admin_username)
    if result.locked_admin_candidates:
        table.add_row(
            "Skipped (locked)",
            ", ".join(result.locked_admin_candidates),
        )
    table.add_row("Login", result.login_outcome.value)
    table.add_row(
        "Password reset performed",
        "yes" if result.password_reset_performed else "no",
    )
    table.add_row(
        "Users (visible)",
        ", ".join(result.usernames) if result.usernames else "(none)",
    )
    table.add_row(
        "Users (expected)",
        ", ".join(result.validation.expected),
    )
    if result.validation.missing:
        table.add_row("Missing", ", ".join(result.validation.missing))
    if result.validation.unexpected:
        table.add_row("Unexpected", ", ".join(result.validation.unexpected))
    table.add_row(
        "Validation",
        "pass" if result.validation.ok else "fail",
    )
    console.print(table)
    raise SystemExit(0 if result.validation.ok else 1)


@app_app.command("compliance-settings")
def app_compliance_settings(
    port: int = typer.Option(DEFAULT_CDP_PORT, "--port", "-p"),
    attach_only: bool = typer.Option(
        False,
        "--attach-only",
        help="Attach to an app already running with CDP (do not launch).",
    ),
    log_file: Path | None = _LOG_FILE_OPTION,
) -> None:
    """Log in, expand Compliance Ready settings, compare App UI to robot APIs."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    connection = None
    try:
        if attach_only:
            connection = attach_to_app(debug_port=port)
        else:
            connection = launch_and_attach(
                debug_port=port,
                quiet=log_file is None,
                log_file=log_file,
            )
        result = run_compliance_settings_scenario(
            connection.page,
            settings=settings,
        )
    except PasswordExpiredError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise SystemExit(3) from exc
    except (RuntimeError, TimeoutError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc
    finally:
        if connection is not None:
            connection.close()

    table = Table(title="Compliance settings (App vs API)", show_header=False)
    table.add_row("Robot", result.robot_name)
    table.add_row("Admin", result.admin_username)
    if result.locked_admin_candidates:
        table.add_row(
            "Skipped (locked)",
            ", ".join(result.locked_admin_candidates),
        )
    table.add_row("Login", result.login_outcome.value)
    table.add_row(
        "UI max login attempts",
        str(result.ui_auth.max_number_of_login_attempts),
    )
    table.add_row(
        "API max login attempts",
        str(result.api_auth.max_number_of_login_attempts),
    )
    table.add_row(
        "UI idle logout (mins)",
        str(result.ui_auth.idle_logout_minutes),
    )
    table.add_row(
        "API idle logout (secs)",
        str(result.api_auth.idle_logout),
    )
    table.add_row(
        "Auth mismatches",
        format_mismatches(result.validation.auth_mismatches),
    )
    table.add_row(
        "Audit mismatches",
        format_mismatches(result.validation.audit_mismatches),
    )
    table.add_row(
        "Validation",
        "pass" if result.validation.ok else "fail",
    )
    console.print(table)
    raise SystemExit(0 if result.validation.ok else 1)
