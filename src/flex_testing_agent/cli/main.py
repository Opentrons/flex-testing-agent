"""CLI entrypoint: ``flex-test``."""

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
from flex_testing_agent.logging import configure_logging, get_logger
from flex_testing_agent.orchestration.discover import (
    RobotDiscoveryError,
    settings_with_resolved_host,
)
from flex_testing_agent.releases.catalog import FlexReleaseCatalog
from flex_testing_agent.releases.client import fetch_flex_release_summary
from flex_testing_agent.releases.urls import ReleaseChannel
from flex_testing_agent.releases.versions import (
    classify_stability,
    normalize_robot_version,
    stack_tag_for_version,
)
from flex_testing_agent.scenarios.install_runner import run_install
from flex_testing_agent.scenarios.runner import run_inspect_scenario

app = typer.Typer(
    name="flex-test",
    help="Local robot-testing harness for Opentrons Flex (Kansas).",
    no_args_is_help=True,
)
console = Console()
log = get_logger(__name__)


async def _resolve_settings_for_robot(settings: Settings) -> Settings:
    """Bind ROBOT_HOST to a live candidate (DHCP-safe)."""
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


_SCENARIO_OPTION = typer.Option(
    None,
    "--scenario",
    help="Optional path to inspect scenario YAML metadata.",
)
_CHANNEL_OPTION = typer.Option(
    None,
    "--channel",
    help="Limit to internal or external (default: both).",
)
_PICTURE_OPTION = typer.Option(
    None,
    "--picture",
    help="Destination path for the JPEG (default: artifacts/camera/).",
)
_PROTOCOL_OPTION = typer.Option(
    None,
    "--protocol",
    help="Protocol file for fixture upload (default: pyro_smoke_no_motion.py).",
)
_RUN_STATE_OPTION = typer.Option(
    None,
    "--run-state",
    help=(
        "Required protocol-run presence: any | no-current | current-idle. "
        "Defaults differ by command (see docs/crs-testing.md)."
    ),
)
_ENSURE_RUN_STATE_OPTION = typer.Option(
    False,
    "--ensure-run-state",
    help=(
        "Mutate the robot into --run-state when mismatched "
        "(requires ALLOW_MUTATIONS=true)."
    ),
)
_SEED_OPTION = typer.Option(
    None,
    "--seed",
    help=(
        "Seed id to run (repeatable). Default: all. "
        "Ids: simple_home_move, complex_transfer_dry, heater_shaker_brief, "
        "cancel_mid_run, camera_and_comments, failed_intentional, idle_current, "
        "pause_mid_run, lpc_scripted."
    ),
)
_INSTALLED_OPTION = typer.Option(
    None,
    "--installed",
    help=(
        "Optional robot OS version from inspect/health to classify "
        "(e.g. 4.0.0-alpha.5 or ot3@4.0.0-alpha.5)."
    ),
)


def _print_channel_latest(catalog: FlexReleaseCatalog) -> None:
    title = f"Flex robot OS — {catalog.channel.value}"
    table = Table(title=title, show_header=True)
    table.add_column("Lane")
    table.add_column("Version")
    table.add_column("Stack tag")
    table.add_column("Manifest")
    if catalog.error:
        console.print(f"[red]{catalog.channel.value}: {catalog.error}[/red]")
        return
    for label, entry in (
        ("stable", catalog.latest.stable),
        ("alpha", catalog.latest.alpha),
        ("beta", catalog.latest.beta),
    ):
        table.add_row(
            label,
            entry.version if entry else "—",
            entry.stack_tag if entry else "—",
            entry.manifest_bucket if entry else "—",
        )
    console.print(table)
    console.print(f"[dim]{catalog.manifest_url}[/dim]")
    console.print(
        f"[dim]Parsed {len(catalog.entries)} release keys "
        f"(production + productionV2 merge).[/dim]\n"
    )


def _print_inspect_summary(
    *,
    robot_name: str,
    host: str,
    connectivity: bool,
    software_version: str | None,
    api_version: str | None,
    update_server_version: str | None,
    access_control: str,
    health_status: str,
    run_id: str,
    evidence_directory: Path | None,
) -> None:
    table = Table(title="Flex Inspect Summary", show_header=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Robot name", robot_name)
    table.add_row("Robot host", host)
    table.add_row("Connectivity", "ok" if connectivity else "unreachable")
    table.add_row("Installed software version", software_version or "unknown")
    table.add_row("API version", api_version or "unknown")
    table.add_row("Update server version", update_server_version or "unknown")
    table.add_row("Access control", access_control)
    table.add_row("Health status", health_status)
    table.add_row("Run identifier", run_id)
    table.add_row(
        "Evidence directory",
        str(evidence_directory) if evidence_directory else "n/a",
    )
    console.print(table)


@app.command("inspect")
def inspect_command(
    scenario: Path | None = _SCENARIO_OPTION,
) -> None:
    """Connect to the configured Flex and capture a read-only snapshot."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        try:
            ctx, snapshot, metadata = await run_inspect_scenario(
                resolved,
                scenario_path=scenario,
            )
        except Exception as exc:
            log.exception("inspect_failed")
            console.print(f"[red]Inspect failed: {exc}[/red]")
            return 1

        health_status = "unknown"
        if snapshot.health is not None:
            health_status = "healthy" if snapshot.health.is_healthy else "degraded"
        elif not snapshot.connectivity:
            health_status = "unreachable"

        update_server_version = None
        if snapshot.update_health is not None:
            update_server_version = snapshot.update_health.update_server_version

        _print_inspect_summary(
            robot_name=snapshot.robot_display_name,
            host=snapshot.host,
            connectivity=snapshot.connectivity,
            software_version=snapshot.installed_software_version,
            api_version=snapshot.api_version,
            update_server_version=update_server_version,
            access_control=snapshot.access_control.state.value,
            health_status=health_status,
            run_id=ctx.run_id,
            evidence_directory=ctx.evidence_directory,
        )
        if snapshot.errors:
            console.print("[yellow]Partial errors:[/yellow]")
            for err in snapshot.errors:
                console.print(f"  - {err}")
        console.print(f"[dim]Scenario: {metadata.name}[/dim]")
        return 0 if snapshot.connectivity else 1

    raise SystemExit(asyncio.run(_run()))


@app.command("install")
def install_command(
    version: str = typer.Argument(
        ...,
        help="Flex robot OS version to install (e.g. 9.1.2-alpha.0).",
    ),
    channel: str | None = _CHANNEL_OPTION,
) -> None:
    """Download and install a published Flex robot OS build (mutates robot).

    Requires ALLOW_MUTATIONS=true. Example::

        ALLOW_MUTATIONS=true uv run flex-test install 9.1.2-alpha.0
    """
    raise SystemExit(_run_install(version, channel))


@app.command("put")
def put_command(
    version: str = typer.Argument(
        ...,
        help="Flex robot OS version to put on the robot (alias for install).",
    ),
    channel: str | None = _CHANNEL_OPTION,
) -> None:
    """Alias for ``install``: put the robot on a published OS version."""
    raise SystemExit(_run_install(version, channel))


def _run_install(version: str, channel: str | None) -> int:
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    if channel is not None and channel not in {"internal", "external"}:
        console.print("[red]--channel must be 'internal' or 'external'[/red]")
        return 2
    if not settings.allow_mutations:
        console.print(
            "[red]ALLOW_MUTATIONS=false. Refusing to install. "
            "Set ALLOW_MUTATIONS=true to proceed.[/red]"
        )
        return 2

    channel_enum = ReleaseChannel(channel) if channel else None

    async def _run() -> int:
        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2
        try:
            ctx, result = await run_install(
                resolved,
                version,
                channel=channel_enum,
            )
        except Exception as exc:
            log.exception("install_failed")
            console.print(f"[red]Install failed: {exc}[/red]")
            return 1

        table = Table(title="Flex Install Summary", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("Robot name", resolved.robot_name)
        table.add_row("Robot host", resolved.robot_host)
        table.add_row("Requested version", result.requested_version)
        table.add_row("Channel", result.channel.value)
        table.add_row("Previous version", result.previous_system_version or "unknown")
        table.add_row("Resulting version", result.resulting_system_version or "unknown")
        table.add_row("Succeeded", "yes" if result.succeeded else "no")
        table.add_row("Detail", result.detail)
        table.add_row("Run identifier", ctx.run_id)
        table.add_row(
            "Evidence directory",
            str(ctx.evidence_directory) if ctx.evidence_directory else "n/a",
        )
        console.print(table)
        return 0 if result.succeeded else 1

    return asyncio.run(_run())


@app.command("releases")
def releases_command(
    channel: str | None = _CHANNEL_OPTION,
    installed: str | None = _INSTALLED_OPTION,
) -> None:
    """Show latest Flex robot OS releases from public releases.json manifests.

    Reads internal and external ``ot3-oe/releases.json`` hosts documented by
    Opentrons/robot-stack. Does not mutate the robot.
    """
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    if channel is not None and channel not in {"internal", "external"}:
        console.print("[red]--channel must be 'internal' or 'external'[/red]")
        raise SystemExit(2)

    async def _run() -> int:
        summary = await fetch_flex_release_summary(
            timeout_seconds=settings.robot_request_timeout_seconds,
        )
        if channel in (None, "internal"):
            _print_channel_latest(summary.internal)
        if channel in (None, "external"):
            _print_channel_latest(summary.external)

        if installed:
            normalized = normalize_robot_version(installed)
            stability = classify_stability(installed) if normalized else None
            console.print("[bold]Installed version classification[/bold]")
            if normalized is None or stability is None:
                console.print(
                    f"  Could not parse {installed!r} as a Flex coordinated semver."
                )
            else:
                console.print(f"  Manifest key: {normalized}")
                console.print(f"  Stability:    {stability.value}")
                console.print(
                    "  Internal tag: "
                    f"{stack_tag_for_version(normalized, ReleaseChannel.INTERNAL)}"
                )
                console.print(
                    "  External tag: "
                    f"{stack_tag_for_version(normalized, ReleaseChannel.EXTERNAL)}"
                )

        console.print(
            "[dim]Reference: ROBOT_STACK_REPO_PATH "
            f"({settings.robot_stack_repo_path or './upstream/robot-stack'})[/dim]"
        )
        failed = False
        if channel in (None, "internal") and summary.internal.error:
            failed = True
        if channel in (None, "external") and summary.external.error:
            failed = True
        return 1 if failed else 0

    raise SystemExit(asyncio.run(_run()))


@app.command("module-reconnect")
def module_reconnect_command(
    phase: str = typer.Argument(
        ...,
        help=("Suite B phase: status | b1 | wait-absent | wait-present | smoke"),
    ),
    serial: str | None = typer.Option(
        None,
        "--serial",
        help="Temperature module serial (required for wait-* phases).",
    ),
    timeout: float = typer.Option(
        120.0,
        "--timeout",
        help="Seconds to poll for absent/present.",
    ),
    celsius: float = typer.Option(
        25.0,
        "--celsius",
        help="Target C for smoke phase (then deactivate).",
    ),
) -> None:
    """Run temperature-module USB reconnect suite B phases.

    Typical flow::

        uv run flex-test module-reconnect b1
        # unplug USB cable
        uv run flex-test module-reconnect wait-absent --serial TDV...
        # replug USB cable
        uv run flex-test module-reconnect wait-present --serial TDV...
        ALLOW_MUTATIONS=true uv run flex-test module-reconnect smoke --serial TDV...
    """
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    allowed = {"status", "b1", "wait-absent", "wait-present", "smoke"}
    if phase not in allowed:
        console.print(f"[red]phase must be one of {sorted(allowed)}[/red]")
        raise SystemExit(2)

    async def _run() -> int:
        from typing import cast

        from flex_testing_agent.capabilities.module_reconnect import (
            Phase,
            run_suite_b_phase,
        )
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        try:
            async with FlexRobot(resolved) as robot:
                result = await run_suite_b_phase(
                    robot,
                    cast(Phase, phase),
                    serial=serial,
                    timeout_seconds=timeout,
                    smoke_celsius=celsius,
                )
        except Exception as exc:
            console.print(f"[red]{phase} failed: {exc}[/red]")
            return 1

        style = "green" if result.passed else "red"
        verdict = "PASS" if result.passed else "FAIL"
        console.print(f"[{style}]{phase}: {verdict}[/{style}]")
        console.print(result.detail)
        if result.elapsed_seconds is not None:
            console.print(f"[dim]elapsed {result.elapsed_seconds:.1f}s[/dim]")
        if result.inventory:
            for mod in result.inventory.get("modules", []):
                console.print(
                    f"  - {mod.get('serialNumber')} "
                    f"{mod.get('moduleModel')} "
                    f"status={mod.get('status')} "
                    f"temp={mod.get('currentTemperature')}"
                )
        return 0 if result.passed else 1

    raise SystemExit(asyncio.run(_run()))


@app.command("run-state")
def run_state_command(
    ensure: str | None = typer.Option(
        None,
        "--ensure",
        help=(
            "Mutate into this state: no-current | current-idle (needs ALLOW_MUTATIONS)."
        ),
    ),
) -> None:
    """Show (or ensure) protocol-run presence used by CRS suites."""
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.orchestration.run_state import (
            DesiredRunState,
            ensure_run_state,
            parse_desired_run_state,
            snapshot_run_state,
        )
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        async with FlexRobot(resolved) as robot:
            try:
                if ensure is None:
                    snap = await snapshot_run_state(robot)
                else:
                    desired = parse_desired_run_state(ensure)
                    if desired is DesiredRunState.ANY:
                        console.print("[red]--ensure any is a no-op[/red]")
                        return 2
                    snap = await ensure_run_state(
                        robot,
                        desired,
                        ensure=True,
                        capability_name="cli_run_state",
                    )
            except Exception as exc:
                console.print(f"[red]{exc}[/red]")
                return 2

        table = Table(title="Protocol run state", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        for label, value in (
            ("Summary", snap.describe()),
            ("Has current", snap.has_current),
            ("Current run id", snap.current_run_id),
            ("Current status", snap.current_status),
            ("Run count", snap.run_count),
            ("links.current", snap.links_current_href),
        ):
            table.add_row(label, "n/a" if value is None else str(value))
        console.print(table)
        return 0

    raise SystemExit(asyncio.run(_run()))


@app.command("probe")
def probe_command(
    no_picture: bool = typer.Option(
        False,
        "--no-picture",
        help="Skip camera capture (probe is read-only without a picture).",
    ),
    picture: Path | None = _PICTURE_OPTION,
    run_state: str | None = _RUN_STATE_OPTION,
    ensure_run_state: bool = _ENSURE_RUN_STATE_OPTION,
) -> None:
    """Exercise catalogued read-only endpoints and optionally take a photo.

    Default run presence: no-current (required for a healthy camera picture).
    Camera capture requires ALLOW_MUTATIONS=true (enables camera if needed).
    """
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.capabilities.probe import probe_robot
        from flex_testing_agent.orchestration.run_state import (
            DesiredRunState,
            parse_desired_run_state,
        )
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        desired = (
            parse_desired_run_state(run_state)
            if run_state is not None
            else DesiredRunState.NO_CURRENT
        )

        async with FlexRobot(resolved) as robot:
            try:
                result = await probe_robot(
                    robot,
                    take_picture=not no_picture,
                    picture_path=picture,
                    run_state=desired,
                    ensure_run_state_flag=ensure_run_state,
                )
            except Exception as exc:
                console.print(f"[red]{exc}[/red]")
                return 2

        summary = result.summary
        table = Table(title="KansasFLEX State Summary", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        for label, value in (
            ("Name", summary.name),
            ("Host", summary.host),
            ("Model", summary.robot_model),
            ("Serial", summary.serial),
            ("System version", summary.system_version),
            ("API version", summary.api_version),
            ("Update server", summary.update_server_version),
            ("Access control", _compact(summary.access_control)),
            ("Run state", result.run_state.describe() if result.run_state else None),
            ("E-stop", _compact(summary.estop)),
            ("Door", _compact(summary.door)),
            ("Lights", _compact(summary.lights)),
            ("Motors engaged", _compact(summary.motors_engaged)),
            ("Instruments", _compact_count(summary.instruments)),
            ("Modules", _compact_count(summary.modules)),
            ("Runs", summary.runs_count),
            ("Protocols", summary.protocols_count),
            ("Maintenance run", _compact(summary.current_maintenance_run)),
            ("Networking", _compact(summary.networking)),
            ("Camera", _compact(summary.camera)),
            ("Camera stream", _compact(summary.camera_stream)),
            ("System time", _compact(summary.system_time)),
            ("Probe OK", f"{summary.probe_ok}"),
            ("Probe failed", f"{summary.probe_failed}"),
        ):
            table.add_row(label, "n/a" if value is None else str(value))
        console.print(table)

        if summary.failed_endpoints:
            console.print("[yellow]Failed endpoints:[/yellow]")
            for item in summary.failed_endpoints:
                console.print(f"  - {item}")

        if result.picture_path:
            console.print(f"[green]Picture saved:[/green] {result.picture_path}")
        elif not no_picture:
            console.print(
                f"[yellow]Picture failed:[/yellow] {result.picture_error or 'unknown'}"
            )

        return 0 if summary.probe_failed == 0 else 1

    raise SystemExit(asyncio.run(_run()))


@app.command("api-suite")
def api_suite_command(
    no_picture: bool = typer.Option(
        False,
        "--no-picture",
        help="Skip Tier A camera capture.",
    ),
    no_create_fixtures: bool = typer.Option(
        False,
        "--no-create-fixtures",
        help="Do not upload protocol/CSV / create run for Tier B.",
    ),
    protocol: Path | None = _PROTOCOL_OPTION,
) -> None:
    """CRS-off Tier A + B + C with timing JSON (ALLOW_MUTATIONS required).

    Order: probe (no-current) → parameterized GETs (current-idle) →
    reversible mutations (no-current). See docs/crs-testing.md.
    """
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.capabilities.api_suite import run_api_suite
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        async with FlexRobot(resolved) as robot:
            try:
                result = await run_api_suite(
                    robot,
                    take_picture=not no_picture,
                    create_fixtures=not no_create_fixtures,
                    protocol_path=protocol,
                )
            except Exception as exc:
                console.print(f"[red]{exc}[/red]")
                return 2

        table = Table(title="API suite (CRS-off A/B/C)")
        table.add_column("Tier")
        table.add_column("OK")
        table.add_column("Failed")
        table.add_column("Notes")
        counts = result.counts
        table.add_row(
            "A probe",
            str(counts.get("tier_a_ok")),
            str(counts.get("tier_a_failed")),
            (result.tier_a.picture_error if result.tier_a else None) or "",
        )
        table.add_row(
            "B parameterized",
            str(counts.get("tier_b_ok")),
            str(counts.get("tier_b_failed")),
            f"skipped={counts.get('tier_b_skipped')}",
        )
        table.add_row(
            "C mutations",
            str(counts.get("tier_c_ok")),
            str(counts.get("tier_c_failed")),
            "",
        )
        console.print(table)
        if result.detail:
            console.print(f"[yellow]{result.detail}[/yellow]")
        if result.timing_path:
            console.print(f"timing={result.timing_path}")
        return 0 if result.ok else 1

    raise SystemExit(asyncio.run(_run()))


@app.command("crs-off-b")
def crs_off_b_command(
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
    """CRS-off Tier B: probe parameterized GET endpoints with fixtures.

    Default run presence: current-idle.
    """
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.capabilities.crs_off import run_crs_off_tier_b
        from flex_testing_agent.orchestration.run_state import (
            DesiredRunState,
            parse_desired_run_state,
        )
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        desired = (
            parse_desired_run_state(run_state)
            if run_state is not None
            else DesiredRunState.CURRENT_IDLE
        )

        async with FlexRobot(resolved) as robot:
            try:
                result = await run_crs_off_tier_b(
                    robot,
                    create_fixtures=create_fixtures,
                    protocol_path=protocol,
                    run_state=desired,
                    ensure_run_state_flag=ensure_run_state,
                )
            except Exception as exc:
                console.print(f"[red]{exc}[/red]")
                return 2

        table = Table(title="CRS-off Tier B", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        for label, value in (
            ("Run state", result.run_state.describe() if result.run_state else None),
            ("Protocol", result.fixtures.get("protocol_id")),
            ("Analysis", result.fixtures.get("analysis_id")),
            ("Run", result.fixtures.get("run_id")),
            ("Data file", result.fixtures.get("data_file_id")),
            ("Created", result.created_resources or None),
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

    raise SystemExit(asyncio.run(_run()))


@app.command("crs-off-c")
def crs_off_c_command(
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
    """CRS-off Tier C: reversible mutations (lights + clientData).

    Requires ALLOW_MUTATIONS=true. Default run presence: no-current.
    Restores light state and deletes the clientData key afterward.
    """
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.capabilities.crs_off import run_crs_off_tier_c
        from flex_testing_agent.orchestration.run_state import (
            DesiredRunState,
            parse_desired_run_state,
        )
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        desired = (
            parse_desired_run_state(run_state)
            if run_state is not None
            else DesiredRunState.NO_CURRENT
        )

        async with FlexRobot(resolved) as robot:
            try:
                result = await run_crs_off_tier_c(
                    robot,
                    run_state=desired,
                    ensure_run_state_flag=ensure_run_state,
                )
            except Exception as exc:
                console.print(f"[red]{exc}[/red]")
                return 2

        if result.run_state is not None:
            console.print(f"[dim]Run state: {result.run_state.describe()}[/dim]")
        table = Table(title="CRS-off Tier C", show_header=True)
        table.add_column("Step")
        table.add_column("OK")
        table.add_column("Detail")
        for step in result.steps:
            table.add_row(
                step.name,
                "yes" if step.ok else "no",
                step.detail or "",
            )
        console.print(table)
        console.print(f"OK={result.ok_count} failed={result.fail_count}")
        return 0 if result.fail_count == 0 else 1

    raise SystemExit(asyncio.run(_run()))


@app.command("seed-runs")
def seed_runs_command(
    seed: list[str] | None = _SEED_OPTION,
    no_fw_update: bool = typer.Option(
        False,
        "--no-fw-update",
        help="Skip subsystem firmware updates even when fw_update_needed.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Stop after the first failing seed.",
    ),
) -> None:
    """Build known run history with live dry-deck motion (PHYSICAL_MOTION).

    Requires ALLOW_MUTATIONS=true and an explicit operator request. Deck must
    be clear except trash A3 and heater-shaker D1. See
    docs/known-state-and-latency.md.
    """
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.capabilities.seed_runs import (
            parse_seed_ids,
            run_seed_runs,
        )
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
            seed_ids = parse_seed_ids(seed)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        async with FlexRobot(resolved) as robot:
            try:
                result = await run_seed_runs(
                    robot,
                    seed_ids=seed_ids,
                    update_firmware=not no_fw_update,
                    strict=strict,
                )
            except Exception as exc:
                console.print(f"[red]{exc}[/red]")
                return 2

        console.print(f"[dim]Preflight:[/dim] {result.preflight}")
        table = Table(title="Seed runs")
        table.add_column("Seed")
        table.add_column("OK")
        table.add_column("Status")
        table.add_column("Run")
        table.add_column("Detail")
        for outcome in result.outcomes:
            table.add_row(
                outcome.seed_id,
                "yes" if outcome.ok else "no",
                outcome.final_status or "",
                (outcome.run_id or "")[:8],
                (outcome.detail or outcome.camera_error or "")[:80],
            )
        console.print(table)
        console.print(
            f"OK={result.ok_count} failed={result.fail_count} "
            f"timing={result.timing_path}"
        )
        return 0 if result.fail_count == 0 else 1

    raise SystemExit(asyncio.run(_run()))


@app.command("reset-data")
def reset_data_command(
    deck_configuration: bool = typer.Option(
        False,
        "--deck-configuration",
        help="Also clear deck configuration (usually prefer known-state --deck).",
    ),
) -> None:
    """Clear robot-server data (runs/protocols/offsets via runsHistory).

    Requires ALLOW_MUTATIONS=true. Does not clear SSH authorized keys.
    See docs/known-state-and-latency.md.
    """
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.capabilities.reset_data import reset_robot_data
        from flex_testing_agent.clients.settings_reset import (
            DECK_CONFIGURATION,
            RUNS_HISTORY,
        )
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        options = {RUNS_HISTORY}
        if deck_configuration:
            options.add(DECK_CONFIGURATION)

        async with FlexRobot(resolved) as robot:
            try:
                result = await reset_robot_data(robot, option_ids=options)
            except Exception as exc:
                console.print(f"[red]{exc}[/red]")
                return 2

        console.print(f"[green]Reset options:[/green] {result.options}")
        if result.timing_path:
            console.print(f"[dim]Timing:[/dim] {result.timing_path}")
        return 0

    raise SystemExit(asyncio.run(_run()))


@app.command("known-state")
def known_state_command(
    reset: bool = typer.Option(
        True,
        "--reset/--no-reset",
        help="Clear robot-server data (runsHistory) before deck setup.",
    ),
    deck: bool = typer.Option(
        True,
        "--deck/--no-deck",
        help="Apply KansasFLEX deck config (HS D1, trash A3).",
    ),
    hs_serial: str | None = typer.Option(
        None,
        "--hs-serial",
        help="Heater-shaker serial for deck config (default: discover or lab serial).",
    ),
) -> None:
    """Baseline known state: reset data + deck config (no protocol play).

    Requires ALLOW_MUTATIONS=true. Seed runs / LPC / motion are separate
    (docs/known-state-and-latency.md).
    """
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run() -> int:
        from flex_testing_agent.capabilities.known_state import setup_known_state
        from flex_testing_agent.robots.flex import FlexRobot

        try:
            resolved = await _resolve_settings_for_robot(settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2

        async with FlexRobot(resolved) as robot:
            try:
                result = await setup_known_state(
                    robot,
                    reset_data=reset,
                    apply_deck=deck,
                    heater_shaker_serial=hs_serial,
                )
            except Exception as exc:
                console.print(f"[red]{exc}[/red]")
                return 2

        table = Table(title="Known state setup", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        for label, value in (
            ("Reset", result.reset_options),
            ("Deck applied", result.deck_applied),
            ("HS serial", result.heater_shaker_serial),
            ("Timing", result.timing_path),
            ("Details", "; ".join(result.details) or None),
        ):
            table.add_row(label, "n/a" if value is None else str(value))
        console.print(table)
        return 0

    raise SystemExit(asyncio.run(_run()))


@app.command("timing")
def timing_command(
    limit: int = typer.Option(10, "--limit", help="Max reports to list."),
) -> None:
    """List recent timing JSON reports under ARTIFACT_DIRECTORY/timing/."""
    clear_settings_cache()
    settings = get_settings()
    from flex_testing_agent.orchestration.timing import load_timing_reports

    directory = settings.ensure_artifact_directory() / "timing"
    reports = load_timing_reports(directory)
    if not reports:
        console.print(f"[yellow]No timing reports in {directory}[/yellow]")
        raise SystemExit(0)

    table = Table(title=f"Timing reports ({directory})")
    table.add_column("Label")
    table.add_column("Created")
    table.add_column("Version")
    table.add_column("Spans")
    for report in reports[-limit:]:
        span_bits = []
        for span in report.spans[:6]:
            dur = (
                f"{span.duration_seconds:.2f}s"
                if span.duration_seconds is not None
                else "?"
            )
            span_bits.append(f"{span.name}={dur}")
        table.add_row(
            report.label,
            report.created_at,
            report.system_version or "n/a",
            ", ".join(span_bits) or "(none)",
        )
    console.print(table)
    raise SystemExit(0)


@app.command("version")
def version_command() -> None:
    """Print package version."""
    from flex_testing_agent import __version__

    console.print(__version__)


def _compact(value: object) -> str | None:
    """Short string for nested JSON API payloads."""
    if value is None:
        return None
    if isinstance(value, dict):
        data = value.get("data", value)
        if isinstance(data, dict):
            parts = [f"{k}={v}" for k, v in list(data.items())[:8]]
            return ", ".join(parts) if parts else "{}"
        return str(data)
    return str(value)


def _compact_count(value: object) -> str | None:
    """Summarize list-shaped API payloads as a count plus brief ids."""
    if value is None:
        return None
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        items = value["data"]
        if not items:
            return "0"
        ids: list[str] = []
        for item in items[:5]:
            if isinstance(item, dict):
                ids.append(str(item.get("id") or item.get("mount") or item))
            else:
                ids.append(str(item))
        suffix = f" ({', '.join(ids)})" if ids else ""
        return f"{len(items)}{suffix}"
    return _compact(value)


def main() -> None:
    """Console script entrypoint."""
    app()


if __name__ == "__main__":
    main()
