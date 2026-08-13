"""``flex-test crs``: CRS-on HTTPS trust and user fixture provisioning."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from flex_testing_agent.capabilities.crs_auth_settings_suite import (
    parse_case_ids,
    run_auth_settings_suite,
)
from flex_testing_agent.capabilities.crs_on import (
    run_enable_crs,
    run_provision_users,
    run_trust_ca,
)
from flex_testing_agent.capabilities.crs_on_lockdown import (
    LockdownActor,
    run_crs_on_lockdown,
)
from flex_testing_agent.capabilities.crs_on_matrix import run_auth_matrix
from flex_testing_agent.capabilities.crs_on_probe import probe_crs_on
from flex_testing_agent.capabilities.crs_on_suite import run_crs_on_suite
from flex_testing_agent.capabilities.crs_on_tier_b import run_crs_on_tier_b
from flex_testing_agent.capabilities.crs_on_tier_c import run_crs_on_tier_c
from flex_testing_agent.capabilities.user_management_suite import (
    run_user_management_suite,
)
from flex_testing_agent.config.settings import Settings, get_settings
from flex_testing_agent.fixtures.crs_users import default_crs_user_fixtures
from flex_testing_agent.orchestration.discover import (
    RobotDiscoveryError,
    settings_with_resolved_host,
)
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    parse_desired_run_state,
)
from flex_testing_agent.robots.flex import FlexRobot

console = Console()
crs_app = typer.Typer(
    name="crs",
    help="CRS-on setup: HTTPS CA trust and test user fixtures.",
    no_args_is_help=True,
)

_TRUST_CA_PASSWORD_OPTION = typer.Option(
    None,
    "--password",
    help=(
        "ODD Robot Encryption Key (rotating; read from Robot Settings on ODD). "
        "Not the CRS service PIN {serial}-0000."
    ),
)
_FIXTURE_OPTION = typer.Option(
    None,
    "--fixture",
    help="Alternate crs_users.yaml path.",
)
_REPLACE_OPTION = typer.Option(
    False,
    "--replace",
    help="Attempt create even when user already exists.",
)
_CONFIRM_ONE_WAY_OPTION = typer.Option(
    False,
    "--confirm-one-way",
    help="Required. CRS enable is one-way; cannot disable via API.",
)
_SKIP_PROVISION_OPTION = typer.Option(
    False,
    "--skip-provision",
    help="Enable CRS only; do not create flex_test_* fixture users.",
)
_AS_USER_OPTION = typer.Option(
    "flex_test_operator",
    "--as-user",
    help="CRS fixture username for OAuth (flex_test_operator, flex_test_service, …).",
)
_AS_SERVICE_USER_OPTION = typer.Option(
    "flex_test_service",
    "--as-user",
    help=(
        "CRS fixture username for OAuth mutations "
        "(default flex_test_service for run_data.write)."
    ),
)
_ENSURE_RUN_STATE_OPTION = typer.Option(
    False,
    "--ensure-run-state",
    help="Uncurrent protocol run before probing if needed.",
)
_PROTOCOL_OPTION = typer.Option(
    None,
    "--protocol",
    help="Override smoke protocol path for fixture upload.",
)
_RUN_STATE_OPTION = typer.Option(
    None,
    "--run-state",
    help="Desired run presence (default: current-idle for probe-b).",
)


async def _settings_for_robot() -> Settings:
    settings = get_settings()
    try:
        return await settings_with_resolved_host(settings)
    except RobotDiscoveryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@crs_app.command("show-fixtures")
def show_fixtures() -> None:
    """List CRS test user fixtures from crs_users.yaml."""
    fixture_file = default_crs_user_fixtures()
    table = Table(title="CRS user fixtures")
    table.add_column("Enabled")
    table.add_column("Username")
    table.add_column("Account type")
    table.add_column("Env suffix")
    table.add_column("Notes")
    for user in fixture_file.users:
        table.add_row(
            "yes" if user.enabled else "no",
            user.username,
            user.account_type,
            user.env_suffix,
            (user.notes or "")[:60],
        )
    console.print(table)
    console.print(
        "Passwords: CRS_FIXTURE_PASSWORD or CRS_PASSWORD_{ENV_SUFFIX} in .env"
    )


@crs_app.command("trust-ca")
def trust_ca_cmd(
    password: str | None = _TRUST_CA_PASSWORD_OPTION,
) -> None:
    """Fetch encrypted CA over HTTP, install PEM + registry for HTTPS."""

    async def _run() -> int:
        settings = await _settings_for_robot()
        async with FlexRobot(settings) as robot:
            result = await run_trust_ca(robot, password=password)
        table = Table(title="CRS trust-ca", show_header=False)
        table.add_row("Host", result.robot_host)
        table.add_row("Serial", result.robot_serial)
        table.add_row("PEM", result.pem_path)
        table.add_row("Registry", result.registry_path)
        table.add_row("HTTPS /health", "ok" if result.https_ok else "failed")
        console.print(table)
        if not result.https_ok:
            console.print(
                "[yellow]HTTPS probe failed; set ROBOT_USE_HTTPS=true after "
                "confirming trust.[/yellow]"
            )
        return 0

    raise typer.Exit(asyncio.run(_run()))


@crs_app.command("probe")
def crs_probe_cmd(
    as_user: str = _AS_USER_OPTION,
    ensure_run_state: bool = _ENSURE_RUN_STATE_OPTION,
    skip_baseline: bool = typer.Option(
        False,
        "--skip-baseline",
        help="Skip unauthenticated GET baseline before authenticated probe.",
    ),
    skip_users_api: bool = typer.Option(
        False,
        "--skip-users-api",
        help="Skip auth-server user-management CRUD (GET probe only).",
    ),
) -> None:
    """CRS-on Tier A: GET probe + user-management API (requires ALLOW_MUTATIONS)."""

    async def _run() -> int:
        settings = await _settings_for_robot()
        if not settings.robot_use_https:
            console.print(
                "[yellow]ROBOT_USE_HTTPS is false; set true for CRS-on probes.[/yellow]"
            )
        if not skip_users_api and not settings.allow_mutations:
            console.print(
                "[red]Tier A user-management API requires ALLOW_MUTATIONS=true. "
                "Use --skip-users-api for GET probe only.[/red]"
            )
            return 1
        tier_a, baseline = await probe_crs_on(
            settings,
            username=as_user,
            ensure_run_state_flag=ensure_run_state,
            include_unauth_baseline=not skip_baseline,
            include_user_management=not skip_users_api,
        )
        table = Table(title=f"CRS-on Tier A ({as_user})", show_header=False)
        table.add_row("GET probe OK", str(tier_a.probe_ok))
        table.add_row("GET probe failed", str(tier_a.probe_failed))
        if tier_a.user_management is not None:
            table.add_row("Users API OK", str(tier_a.users_ok))
            table.add_row("Users API failed", str(tier_a.users_failed))
        if baseline is not None:
            table.add_row(
                "Unauth GET unexpected deny",
                str(baseline.unauthenticated_denied),
            )
            table.add_row("Unauth GET OK", str(baseline.unauthenticated_ok))
        console.print(table)
        if tier_a.user_management is not None and tier_a.user_management.steps:
            um_table = Table(title="User-management API")
            um_table.add_column("Step")
            um_table.add_column("Method")
            um_table.add_column("OK")
            um_table.add_column("Detail")
            for step in tier_a.user_management.steps:
                um_table.add_row(
                    step.name,
                    step.method,
                    "yes" if step.ok else "no",
                    step.detail[:60],
                )
            console.print(um_table)
        if tier_a.probe.summary.failed_endpoints:
            console.print("[red]Failed GET endpoints:[/red]")
            for item in tier_a.probe.summary.failed_endpoints[:15]:
                console.print(f"  {item}")
            if len(tier_a.probe.summary.failed_endpoints) > 15:
                console.print(
                    f"  … and {len(tier_a.probe.summary.failed_endpoints) - 15} more"
                )
        return 0 if tier_a.ok else 1

    raise typer.Exit(asyncio.run(_run()))


@crs_app.command("probe-b")
def crs_probe_b_cmd(
    as_user: str = _AS_USER_OPTION,
    create_fixtures: bool = typer.Option(
        False,
        "--create-fixtures",
        help=(
            "Upload smoke protocol / CSV and create a run when fixtures are "
            "missing (requires ALLOW_MUTATIONS=true). Also ensures current-idle."
        ),
    ),
    protocol: Path | None = _PROTOCOL_OPTION,
    run_state: str | None = _RUN_STATE_OPTION,
    ensure_run_state: bool = _ENSURE_RUN_STATE_OPTION,
) -> None:
    """CRS-on Tier B: parameterized GET probe with OAuth (requires CRS enabled)."""

    async def _run() -> int:
        settings = await _settings_for_robot()
        if not settings.robot_use_https:
            console.print(
                "[yellow]ROBOT_USE_HTTPS is false; set true for CRS-on probes.[/yellow]"
            )
        desired = (
            parse_desired_run_state(run_state)
            if run_state is not None
            else DesiredRunState.CURRENT_IDLE
        )
        try:
            result = await run_crs_on_tier_b(
                settings,
                username=as_user,
                create_fixtures=create_fixtures,
                protocol_path=protocol,
                run_state=desired,
                ensure_run_state_flag=ensure_run_state,
            )
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        table = Table(title=f"CRS-on Tier B ({as_user})", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        for label, value in (
            ("Run state", result.run_state.describe() if result.run_state else None),
            ("Protocol", result.fixtures.get("protocol_id")),
            ("Run", result.fixtures.get("run_id")),
            ("Username fixture", result.fixtures.get("username")),
            ("OK", result.ok_count),
            ("Failed", result.fail_count),
            ("Skipped (no fixture)", len(result.skipped_paths)),
        ):
            table.add_row(label, "n/a" if value is None else str(value))
        console.print(table)

        failed = [r for r in result.results if not r.ok]
        if failed:
            console.print("[yellow]Failed parameterized GETs:[/yellow]")
            for item in failed[:30]:
                console.print(
                    f"  - {item.path} ({item.status_code}) {item.error or ''}"
                )
        if result.skipped_paths:
            console.print(
                f"[dim]Skipped {len(result.skipped_paths)} paths "
                "(missing path params)[/dim]"
            )
        return 0 if result.fail_count == 0 else 1

    raise typer.Exit(asyncio.run(_run()))


@crs_app.command("probe-c")
def crs_probe_c_cmd(
    as_user: str = _AS_SERVICE_USER_OPTION,
    run_state: str | None = _RUN_STATE_OPTION,
    ensure_run_state: bool = typer.Option(
        True,
        "--ensure-run-state/--no-ensure-run-state",
        help=(
            "Put the robot in the desired run state before Tier C "
            "(default: on; needs ALLOW_MUTATIONS)."
        ),
    ),
) -> None:
    """CRS-on Tier C: reversible mutations with OAuth (requires ALLOW_MUTATIONS)."""

    async def _run() -> int:
        settings = await _settings_for_robot()
        if not settings.robot_use_https:
            console.print(
                "[yellow]ROBOT_USE_HTTPS is false; set true for CRS-on probes.[/yellow]"
            )
        desired = (
            parse_desired_run_state(run_state)
            if run_state is not None
            else DesiredRunState.NO_CURRENT
        )
        try:
            result = await run_crs_on_tier_c(
                settings,
                username=as_user,
                run_state=desired,
                ensure_run_state_flag=ensure_run_state,
            )
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        table = Table(title=f"CRS-on Tier C ({as_user})", show_header=False)
        table.add_column("Step")
        table.add_column("OK")
        table.add_column("Detail")
        for step in result.steps:
            table.add_row(
                step.name,
                "yes" if step.ok else "no",
                (step.detail or "")[:60],
            )
        console.print(table)
        if result.run_state is not None:
            console.print(f"Run state: {result.run_state.describe()}")
        console.print(f"OK={result.ok_count} failed={result.fail_count}")
        return 0 if result.fail_count == 0 else 1

    raise typer.Exit(asyncio.run(_run()))


@crs_app.command("suite")
def crs_suite_cmd(
    as_user: str = _AS_SERVICE_USER_OPTION,
    skip_auth_matrix: bool = typer.Option(
        False,
        "--skip-auth-matrix",
        help="Skip scoped GET authorization matrix at suite start.",
    ),
    include_lockdown: bool = typer.Option(
        False,
        "--include-lockdown",
        help="Run CRS-on negative auth lockdown (L1 parameter-free) before the suite.",
    ),
    include_baseline: bool = typer.Option(
        False,
        "--include-baseline",
        help="Include unauthenticated GET baseline before Tier A probe.",
    ),
    protocol: Path | None = _PROTOCOL_OPTION,
) -> None:
    """CRS-on full suite: optional lockdown + auth matrix + Tier A + B + C."""

    async def _run() -> int:
        settings = await _settings_for_robot()
        if not settings.robot_use_https:
            console.print(
                "[yellow]ROBOT_USE_HTTPS is false; set true for CRS-on suite.[/yellow]"
            )
        try:
            result = await run_crs_on_suite(
                settings,
                username=as_user,
                include_auth_matrix=not skip_auth_matrix,
                include_unauth_baseline=include_baseline,
                include_lockdown=include_lockdown,
                create_fixtures=True,
                protocol_path=protocol,
            )
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        table = Table(title=f"CRS-on suite ({as_user})")
        table.add_column("Tier")
        table.add_column("OK")
        table.add_column("Failed")
        table.add_column("Notes")
        counts = result.counts
        suite_rows = (
            (
                "Lockdown preflight",
                "lockdown_ok",
                "lockdown_failed",
                "lockdown_hard_failed",
            ),
            (
                "Auth matrix",
                "auth_matrix_ok",
                "auth_matrix_failed",
                "auth_matrix_skipped",
            ),
            (
                "A GET + users",
                "tier_a_ok",
                "tier_a_failed",
                "tier_a_users_ok",
            ),
            ("B parameterized", "tier_b_ok", "tier_b_failed", "tier_b_skipped"),
            ("C mutations", "tier_c_ok", "tier_c_failed", None),
        )
        for label, ok_key, fail_key, notes_key in suite_rows:
            ok_val = counts.get(ok_key)
            fail_val = counts.get(fail_key)
            if label == "A GET + users":
                notes = (
                    f"get={counts.get('tier_a_probe_ok', 0)} "
                    f"users={counts.get('tier_a_users_ok', 0)}"
                )
            elif label == "Lockdown preflight":
                if counts.get("lockdown_ok") is None:
                    notes = "skipped"
                else:
                    notes = (
                        f"hard={counts.get('lockdown_hard_failed', 0)} "
                        f"leaks={counts.get('lockdown_leaks', 0)}"
                    )
            elif notes_key and counts.get(notes_key) is not None:
                notes = f"skipped={counts.get(notes_key)}"
            else:
                notes = ""
            table.add_row(
                label,
                str(ok_val) if ok_val is not None else "n/a",
                str(fail_val) if fail_val is not None else "n/a",
                notes,
            )
        console.print(table)
        if result.detail:
            console.print(f"[yellow]{result.detail}[/yellow]")
        if result.timing_path:
            console.print(f"timing={result.timing_path}")
        summary_path = settings.ensure_artifact_directory() / "crs_on_suite.json"
        console.print(f"summary={summary_path}")
        return 0 if result.ok else 1

    raise typer.Exit(asyncio.run(_run()))


@crs_app.command("auth-matrix")
def crs_auth_matrix_cmd() -> None:
    """CRS-on authorization matrix for scoped GET endpoints."""

    async def _run() -> int:
        settings = await _settings_for_robot()
        if not settings.robot_use_https:
            console.print(
                "[yellow]ROBOT_USE_HTTPS is false; set true for CRS-on matrix.[/yellow]"
            )
        matrix = await run_auth_matrix(settings)
        table = Table(title="CRS-on auth matrix")
        table.add_column("OK")
        table.add_column("Endpoint")
        table.add_column("Actor")
        table.add_column("Expected")
        table.add_column("Status")
        table.add_column("Detail")
        for row in matrix.results:
            table.add_row(
                "yes" if row.ok else "no",
                row.endpoint,
                row.actor,
                row.expected,
                str(row.status_code),
                (row.detail or "")[:40],
            )
        console.print(table)
        if matrix.skipped:
            console.print(f"[dim]Skipped {len(matrix.skipped)}:[/dim]")
            for item in matrix.skipped:
                console.print(f"  {item}")
        console.print(f"OK={matrix.ok_count} failed={matrix.fail_count}")
        return 0 if matrix.fail_count == 0 else 1

    raise typer.Exit(asyncio.run(_run()))


def _parse_lockdown_actors(raw: str) -> tuple[LockdownActor, ...]:
    actors: list[LockdownActor] = []
    for part in raw.split(","):
        name = part.strip()
        if not name:
            continue
        actors.append(LockdownActor(name))
    if not actors:
        raise typer.BadParameter("Provide at least one actor")
    return tuple(actors)


@crs_app.command("lockdown")
def crs_lockdown_cmd(
    actors: str = typer.Option(
        "none,bad_bearer,malformed_bearer,bad_oauth,auditor,operator",
        "--actors",
        help=(
            "Comma-separated personas: none, bad_bearer, malformed_bearer, "
            "bad_oauth, auditor, operator."
        ),
    ),
    include_parameterized: bool = typer.Option(
        False,
        "--include-parameterized/--parameter-free-only",
        help="Also probe parameterized paths (placeholder or fixture IDs).",
    ),
    create_fixtures: bool = typer.Option(
        False,
        "--create-fixtures",
        help=(
            "With --include-parameterized, seed Tier B fixture IDs instead of "
            "placeholder UUIDs (requires ALLOW_MUTATIONS)."
        ),
    ),
    strict_only: bool = typer.Option(
        False,
        "--strict-only",
        help="Only auth-server and audit-server endpoints (hard-fail enforcement).",
    ),
    show_failures: bool = typer.Option(
        False,
        "--show-failures",
        help="Print failing rows (default: summary only).",
    ),
    protocol: Path | None = _PROTOCOL_OPTION,
) -> None:
    """CRS-on negative auth: no / bad / under-scoped credential probes."""

    async def _run() -> int:
        settings = await _settings_for_robot()
        if not settings.robot_use_https:
            console.print(
                "[yellow]ROBOT_USE_HTTPS is false; "
                "set true for CRS-on lockdown.[/yellow]"
            )
        try:
            parsed_actors = _parse_lockdown_actors(actors)
        except ValueError as exc:
            console.print(f"[red]Invalid --actors: {exc}[/red]")
            return 2

        if create_fixtures and not include_parameterized:
            console.print(
                "[yellow]--create-fixtures requires --include-parameterized[/yellow]"
            )
            return 2

        label = "l3" if strict_only else ("l2" if include_parameterized else "l1")

        result = await run_crs_on_lockdown(
            settings,
            actors=parsed_actors,
            include_parameterized=include_parameterized,
            strict_only=strict_only,
            create_fixtures=create_fixtures,
            protocol_path=protocol,
            label=label,
        )

        if result.oauth_bad_password_ok is not None:
            oauth_style = "green" if result.oauth_bad_password_ok else "red"
            console.print(
                f"[{oauth_style}]bad_oauth POST /auth/oauth2/token → "
                f"{result.oauth_bad_password_status}[/{oauth_style}]"
            )

        if show_failures:
            table = Table(title="CRS-on lockdown failures")
            table.add_column("Endpoint")
            table.add_column("Method")
            table.add_column("Actor")
            table.add_column("Expected")
            table.add_column("Status")
            table.add_column("Detail")
            for row in result.results:
                if row.ok:
                    continue
                table.add_row(
                    row.endpoint,
                    row.method,
                    row.actor,
                    row.expected,
                    str(row.status_code),
                    (row.detail or "")[:60],
                )
            console.print(table)

        console.print(
            f"OK={result.ok_count} failed={result.fail_count} "
            f"hard={len(result.hard_failures())} "
            f"leaks={result.leak_count} skipped={len(result.skipped)}"
        )
        if result.fixtures:
            console.print(f"[dim]fixtures={result.fixtures}[/dim]")
        evidence = (
            settings.ensure_artifact_directory()
            / "pyro-tests"
            / f"crs-on-lockdown-{label}.json"
        )
        console.print(f"evidence={evidence}")
        if result.skipped:
            console.print(f"[dim]Skipped {len(result.skipped)} unresolved paths[/dim]")

        hard_count = len(result.hard_failures())
        if result.oauth_bad_password_ok is False:
            hard_count += 1
        return 0 if hard_count == 0 else 1

    raise typer.Exit(asyncio.run(_run()))


@crs_app.command("enable")
def enable_crs_cmd(
    confirm_one_way: bool = _CONFIRM_ONE_WAY_OPTION,
    skip_provision: bool = _SKIP_PROVISION_OPTION,
    fixture: Path | None = _FIXTURE_OPTION,
) -> None:
    """Enable CRS (one-way), bootstrap admin, and provision fixture users."""

    if not confirm_one_way:
        console.print(
            "[red]Refusing CRS enable without --confirm-one-way "
            "(PATCH accessControlEnabled is irreversible via API).[/red]"
        )
        raise typer.Exit(code=1)

    async def _run() -> int:
        settings = await _settings_for_robot()
        async with FlexRobot(settings) as robot:
            result = await run_enable_crs(
                robot,
                confirm_one_way=True,
                skip_provision=skip_provision,
                fixture_path=str(fixture) if fixture else None,
            )
        table = Table(title="CRS enable", show_header=False)
        table.add_row("Bootstrap admin", result.bootstrap_username)
        table.add_row("Bootstrap created", "yes" if result.bootstrap_created else "no")
        table.add_row("CRS enabled", "yes" if result.crs_enabled else "no")
        if not skip_provision:
            table.add_row(
                "Fixture users",
                f"ok={result.provision.ok_count} failed={result.provision.fail_count}",
            )
        console.print(table)
        if not skip_provision and result.provision.fail_count > 0:
            return 1
        console.print(
            "[yellow]CRS is on. Use ROBOT_USE_HTTPS=true and OAuth for API calls. "
            "Restore: opentrons_disable_crs ({serial}-0000) or EXEC-2176 wipe.[/yellow]"
        )
        return 0

    raise typer.Exit(asyncio.run(_run()))


@crs_app.command("provision-users")
def provision_users_cmd(
    fixture: Path | None = _FIXTURE_OPTION,
    replace: bool = _REPLACE_OPTION,
) -> None:
    """Create enabled CRS test users (requires ALLOW_MUTATIONS)."""

    async def _run() -> int:
        settings = await _settings_for_robot()
        async with FlexRobot(settings) as robot:
            result = await run_provision_users(
                robot,
                fixture_path=str(fixture) if fixture else None,
                replace=replace,
            )
        table = Table(title="CRS provision-users")
        table.add_column("OK")
        table.add_column("Username")
        table.add_column("Type")
        table.add_column("Detail")
        for outcome in result.outcomes:
            table.add_row(
                "yes" if outcome.ok else "no",
                outcome.username,
                outcome.account_type,
                outcome.detail[:80],
            )
        console.print(table)
        console.print(f"OK={result.ok_count} failed={result.fail_count}")
        return 0 if result.fail_count == 0 else 1

    raise typer.Exit(asyncio.run(_run()))


_ADMIN_USER_OPTION = typer.Option(
    "flex_harness_admin",
    "--as-admin",
    help="Bootstrap admin username for user-management CRUD setup.",
)
_OPERATOR_USER_OPTION = typer.Option(
    "flex_test_operator",
    "--as-operator",
    help="Operator fixture username for non-admin 403 checks.",
)


@crs_app.command("users-api")
def users_api_cmd(
    as_admin: str = _ADMIN_USER_OPTION,
    as_operator: str = _OPERATOR_USER_OPTION,
) -> None:
    """Run auth-server user-management CRUD only (subset of Tier A)."""

    async def _run() -> int:
        settings = await _settings_for_robot()
        result = await run_user_management_suite(
            settings,
            admin_username=as_admin,
            operator_username=as_operator,
        )
        table = Table(title=f"CRS user-management API ({as_admin})")
        table.add_column("Step")
        table.add_column("Method")
        table.add_column("Path")
        table.add_column("OK")
        table.add_column("Detail")
        for step in result.steps:
            table.add_row(
                step.name,
                step.method,
                step.path,
                "yes" if step.ok else "no",
                step.detail[:80],
            )
        console.print(table)
        console.print(f"OK={result.ok_count} failed={result.fail_count}")
        return 0 if result.fail_count == 0 else 1

    raise typer.Exit(asyncio.run(_run()))


_SETTINGS_CASES_OPTION = typer.Option(
    None,
    "--cases",
    help=(
        "Comma-separated case ids (S0-S12). "
        "Default: all except S5; S6 needs --include-slow."
    ),
)
_SETTINGS_INCLUDE_SLOW_OPTION = typer.Option(
    False,
    "--include-slow",
    help="Include S5 (passwordResetTime) and S6 (idleLogout wait).",
)
_SETTINGS_RESTORE_OPTION = typer.Option(
    True,
    "--restore-defaults/--no-restore-defaults",
    help="Restore baseline settings captured at S0 after the run.",
)
_SETTINGS_IDLE_WAIT_OPTION = typer.Option(
    65.0,
    "--idle-wait-seconds",
    help="Seconds to wait for S6 idleLogout enforcement.",
)
_SETTINGS_PROTOCOL_OPTION = typer.Option(
    None,
    "--protocol",
    help="Override smoke protocol for S8/S9/S10 upload tests.",
)


@crs_app.command("settings-suite")
def settings_suite_cmd(
    as_admin: str = typer.Option(
        "flex_test_admin",
        "--as-admin",
        help="Admin fixture username for settings mutations.",
    ),
    as_operator: str = typer.Option(
        "flex_test_operator",
        "--as-operator",
        help="Operator fixture username for gate-deny tests.",
    ),
    as_auditor: str = typer.Option(
        "flex_test_auditor",
        "--as-auditor",
        help="Auditor fixture username for S12 read checks.",
    ),
    cases: str | None = _SETTINGS_CASES_OPTION,
    include_slow: bool = _SETTINGS_INCLUDE_SLOW_OPTION,
    restore_defaults: bool = _SETTINGS_RESTORE_OPTION,
    idle_wait_seconds: float = _SETTINGS_IDLE_WAIT_OPTION,
    protocol: Path | None = _SETTINGS_PROTOCOL_OPTION,
) -> None:
    """Run CRS auth settings behavior suite (GET/PATCH /auth/settings)."""

    async def _run() -> int:
        settings = await _settings_for_robot()
        try:
            selected = parse_case_ids(cases)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 1
        result = await run_auth_settings_suite(
            settings,
            admin_username=as_admin,
            operator_username=as_operator,
            auditor_username=as_auditor,
            cases=selected,
            include_slow=include_slow,
            restore_defaults=restore_defaults,
            idle_wait_seconds=idle_wait_seconds,
            protocol_path=protocol,
        )
        table = Table(title=f"CRS auth settings suite ({as_admin})")
        table.add_column("Case")
        table.add_column("Step")
        table.add_column("OK")
        table.add_column("Skipped")
        table.add_column("Detail")
        for step in result.steps:
            table.add_row(
                step.case_id,
                step.name,
                "yes" if step.ok else "no",
                "yes" if step.skipped else "",
                step.detail[:100],
            )
        console.print(table)
        console.print(
            f"OK={result.ok_count} failed={result.fail_count} "
            f"skipped={result.skipped_count}"
        )
        return 0 if result.fail_count == 0 else 1

    raise typer.Exit(asyncio.run(_run()))
