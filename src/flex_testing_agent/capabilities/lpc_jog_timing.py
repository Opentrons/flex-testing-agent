"""LPC-like random-jog timing (PHYSICAL_MOTION) inside a high-Z safe box.

Reuses the scripted LPC HTTP map (maintenance run + virtual tiprack on C2) but
walks many ``moveRelative`` jogs for latency, never toward the deck. See
``fixtures/lpc_jog_space.py`` and ``docs/known-state-and-latency.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.capabilities.seed_lpc import (
    DEFAULT_APPROACH_Z_MM,
    DEFAULT_LABWARE_ID,
    DEFAULT_LABWARE_LOAD_NAME,
    DEFAULT_LABWARE_NAMESPACE,
    DEFAULT_LABWARE_VERSION,
    DEFAULT_PIPETTE_ID,
    DEFAULT_PIPETTE_MOUNT,
    DEFAULT_PIPETTE_NAME,
    DEFAULT_SLOT,
)
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.maintenance_runs import MaintenanceRunsClient
from flex_testing_agent.fixtures.lpc_jog_space import (
    DEFAULT_JOG_COUNT,
    DEFAULT_RNG_SEED,
    DEFAULT_SAVE_EVERY,
    JogLatencyStats,
    JogPlan,
    PlannedJog,
    latency_stats,
    plan_random_jogs,
)
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.timing import TimingSession
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

LPC_JOG_TIMING = CapabilityDescriptor(
    name="lpc_jog_timing",
    description=(
        "LPC-like maintenance-run random jogs inside a high-Z safe box on C2 "
        "with per-jog latency stats. PHYSICAL_MOTION; operator-requested only."
    ),
    risk_level=RiskLevel.PHYSICAL_MOTION,
    mutates_robot=True,
    max_execution_time_seconds=3600.0,
    evidence_produced=["lpc_jog_timing.json", "timing"],
    preconditions=[
        "ALLOW_MUTATIONS=true",
        "Operator confirmed clear deck (--confirm-clear-deck)",
        "Door closed, estop clear, pipette on the requested mount",
        "Slot C2 empty (virtual tiprack only); trash A3 and HS D1 may remain",
    ],
)


class LpcJogTimingResult(BaseModel):
    """Outcome of the LPC jog timing run."""

    ok: bool
    maintenance_run_id: str | None = None
    slot: str = DEFAULT_SLOT
    approach_z_mm: float = DEFAULT_APPROACH_Z_MM
    plan: JogPlan | None = None
    jog_stats: JogLatencyStats | None = None
    save_stats: JogLatencyStats | None = None
    stats_by_axis: list[JogLatencyStats] = Field(default_factory=list)
    timing_path: str | None = None
    preflight: dict[str, Any] = Field(default_factory=dict)
    commands: list[str] = Field(default_factory=list)
    detail: str | None = None


def _data_object(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("data")
    return raw if isinstance(raw, dict) else payload


def _door_is_closed(payload: dict[str, Any]) -> bool:
    data = _data_object(payload)
    return str(data.get("status") or "").lower() == "closed"


def _estop_is_clear(payload: dict[str, Any]) -> bool:
    data = _data_object(payload)
    status = str(data.get("status") or data.get("estopStatus") or "").lower()
    return status in {"disengaged", "notengaged", "ok", "idle"}


def _mount_has_pipette(instruments: list[dict[str, Any]], mount: str) -> bool:
    wanted = mount.lower()
    for item in instruments:
        if str(item.get("mount") or "").lower() != wanted:
            continue
        name = item.get("instrumentName")
        nested = item.get("data")
        if isinstance(nested, dict):
            name = name or nested.get("instrumentName")
        if name:
            return True
        if item.get("ok") is True:
            return True
    return False


async def _run_command(
    client: MaintenanceRunsClient,
    run_id: str,
    command: dict[str, Any],
    *,
    timeout_ms: int = 120_000,
) -> dict[str, Any]:
    payload = await client.enqueue_command(
        run_id,
        command,
        wait_until_complete=True,
        timeout_ms=timeout_ms,
    )
    status = client.command_status(payload)
    if status != "succeeded":
        detail = client.command_error_detail(payload) or f"status={status}"
        raise RobotApiError(
            f"maintenance command {command.get('commandType')} failed: {detail}",
            path=f"/maintenance_runs/{run_id}/commands",
            body=str(payload)[:2000],
        )
    return payload


async def _preflight(
    robot: FlexRobot,
    *,
    pipette_mount: str,
) -> dict[str, Any]:
    notes: list[str] = []
    door = await robot.robot_control.get_door_status()
    if not _door_is_closed(door):
        raise RuntimeError(f"door must be closed before LPC jogs; got {door}")
    notes.append("door=closed")
    estop = await robot.robot_control.get_estop_status()
    if not _estop_is_clear(estop):
        raise RuntimeError(f"estop must be clear before LPC jogs; got {estop}")
    notes.append("estop=clear")
    instruments = await robot.instruments.list_instrument_summaries()
    if not _mount_has_pipette(instruments, pipette_mount):
        raise RuntimeError(
            f"no pipette on mount {pipette_mount!r}; attach one before jogging"
        )
    notes.append(f"pipette_mount={pipette_mount}")
    try:
        current = await robot.maintenance_runs.get_current()
        data = current.get("data")
        if isinstance(data, dict) and data.get("id"):
            await robot.maintenance_runs.delete(str(data["id"]))
            notes.append(f"deleted leftover maintenance run {data['id']}")
    except RobotApiError:
        pass
    return {"ok": True, "notes": notes, "door": door, "estop": estop}


async def _setup_approach(
    maintenance: MaintenanceRunsClient,
    run_id: str,
    *,
    slot: str,
    pipette_name: str,
    pipette_mount: str,
    approach_z_mm: float,
    commands_done: list[str],
) -> None:
    await _run_command(
        maintenance,
        run_id,
        {
            "commandType": "loadPipette",
            "params": {
                "pipetteName": pipette_name,
                "mount": pipette_mount,
                "pipetteId": DEFAULT_PIPETTE_ID,
            },
        },
    )
    commands_done.append("loadPipette")
    await _run_command(
        maintenance,
        run_id,
        {
            "commandType": "loadLabware",
            "params": {
                "location": {"slotName": slot},
                "loadName": DEFAULT_LABWARE_LOAD_NAME,
                "namespace": DEFAULT_LABWARE_NAMESPACE,
                "version": DEFAULT_LABWARE_VERSION,
                "labwareId": DEFAULT_LABWARE_ID,
            },
        },
    )
    commands_done.append("loadLabware")
    await _run_command(
        maintenance,
        run_id,
        {"commandType": "home", "params": {}},
        timeout_ms=180_000,
    )
    commands_done.append("home")
    await _run_command(
        maintenance,
        run_id,
        {
            "commandType": "moveToWell",
            "params": {
                "pipetteId": DEFAULT_PIPETTE_ID,
                "labwareId": DEFAULT_LABWARE_ID,
                "wellName": "A1",
                "wellLocation": {
                    "origin": "top",
                    "offset": {"x": 0, "y": 0, "z": approach_z_mm},
                },
            },
        },
        timeout_ms=180_000,
    )
    commands_done.append("moveToWell")


async def _jog(
    maintenance: MaintenanceRunsClient,
    run_id: str,
    planned: PlannedJog,
    commands_done: list[str],
) -> None:
    await _run_command(
        maintenance,
        run_id,
        {
            "commandType": "moveRelative",
            "params": {
                "pipetteId": DEFAULT_PIPETTE_ID,
                "axis": planned.axis,
                "distance": planned.distance_mm,
            },
        },
    )
    commands_done.append(f"moveRelative:{planned.axis}:{planned.distance_mm:g}")


async def run_lpc_jog_timing(
    robot: FlexRobot,
    *,
    confirm_clear_deck: bool,
    jog_count: int = DEFAULT_JOG_COUNT,
    rng_seed: int = DEFAULT_RNG_SEED,
    save_every: int = DEFAULT_SAVE_EVERY,
    slot: str = DEFAULT_SLOT,
    pipette_name: str = DEFAULT_PIPETTE_NAME,
    pipette_mount: str = DEFAULT_PIPETTE_MOUNT,
    approach_z_mm: float = DEFAULT_APPROACH_Z_MM,
) -> LpcJogTimingResult:
    """Run bounded random LPC jogs and write a timing JSON report."""
    ensure_mutation_allowed(
        robot.settings,
        risk_level=LPC_JOG_TIMING.risk_level,
        capability_name=LPC_JOG_TIMING.name,
    )
    if not confirm_clear_deck:
        raise RuntimeError(
            "Refusing LPC jog timing without --confirm-clear-deck "
            "(slot C2 must be empty; trash A3 and HS D1 may remain)."
        )
    if approach_z_mm < 20.0:
        raise ValueError("approach_z_mm must be >= 20 (stay well above the deck)")

    plan = plan_random_jogs(
        jog_count=jog_count,
        rng_seed=rng_seed,
        save_every=save_every,
    )
    timing = TimingSession(
        label="lpc-jog-timing",
        robot_host=robot.settings.robot_host,
    )
    timing.note(
        f"safe box x=[{plan.box['x']['min_mm']},{plan.box['x']['max_mm']}] "
        f"y=[{plan.box['y']['min_mm']},{plan.box['y']['max_mm']}] "
        f"z=[{plan.box['z']['min_mm']},{plan.box['z']['max_mm']}] mm vs approach"
    )
    try:
        health = await robot.verify_health()
        timing.system_version = health.system_version
        timing.api_version = health.api_version
    except Exception as exc:
        timing.note(f"health: {exc}")

    commands_done: list[str] = []
    preflight: dict[str, Any] = {}
    run_id: str | None = None
    jog_durations: list[float] = []
    save_durations: list[float] = []
    by_axis: dict[str, list[float]] = {"x": [], "y": [], "z": []}

    try:
        async with timing.aspan("lpc.preflight"):
            preflight = await _preflight(robot, pipette_mount=pipette_mount)

        async with timing.aspan("lpc.create_maintenance_run"):
            created = await robot.maintenance_runs.create()
        run_id = robot.maintenance_runs.run_id_from_create(created)
        if run_id is None:
            return LpcJogTimingResult(
                ok=False,
                detail="maintenance run create missing id",
                preflight=preflight,
                plan=plan,
            )

        async with timing.aspan("lpc.setup_approach"):
            await _setup_approach(
                robot.maintenance_runs,
                run_id,
                slot=slot,
                pipette_name=pipette_name,
                pipette_mount=pipette_mount,
                approach_z_mm=approach_z_mm,
                commands_done=commands_done,
            )

        async with timing.aspan("lpc.random_jogs", meta={"jog_count": jog_count}):
            for planned in plan.jogs:
                span_name = f"lpc.jog.{planned.index:03d}.{planned.axis}"
                async with timing.aspan(
                    span_name,
                    meta={
                        "axis": planned.axis,
                        "distance_mm": planned.distance_mm,
                        "x": planned.x_after,
                        "y": planned.y_after,
                        "z": planned.z_after,
                    },
                ):
                    await _jog(robot.maintenance_runs, run_id, planned, commands_done)
                duration = timing.spans[-1].duration_seconds or 0.0
                jog_durations.append(duration)
                by_axis[planned.axis].append(duration)
                if planned.save_position:
                    save_name = f"lpc.savePosition.{planned.index:03d}"
                    async with timing.aspan(save_name):
                        await _run_command(
                            robot.maintenance_runs,
                            run_id,
                            {
                                "commandType": "savePosition",
                                "params": {
                                    "pipetteId": DEFAULT_PIPETTE_ID,
                                    "positionId": f"lpc-jog-{planned.index:03d}",
                                    "failOnNotHomed": False,
                                },
                            },
                        )
                    commands_done.append(f"savePosition:{planned.index}")
                    save_durations.append(timing.spans[-1].duration_seconds or 0.0)

        async with timing.aspan("lpc.return_to_approach"):
            for planned in plan.return_jogs:
                await _jog(robot.maintenance_runs, run_id, planned, commands_done)

        async with timing.aspan("lpc.home"):
            await _run_command(
                robot.maintenance_runs,
                run_id,
                {"commandType": "home", "params": {}},
                timeout_ms=180_000,
            )
            commands_done.append("home")

        jog_summary = latency_stats("moveRelative", jog_durations)
        save_summary = latency_stats("savePosition", save_durations)
        axis_summaries = [
            latency_stats(f"moveRelative.{axis}", by_axis[axis])
            for axis in ("x", "y", "z")
        ]
        result = LpcJogTimingResult(
            ok=True,
            maintenance_run_id=run_id,
            slot=slot,
            approach_z_mm=approach_z_mm,
            plan=plan,
            jog_stats=jog_summary,
            save_stats=save_summary,
            stats_by_axis=axis_summaries,
            preflight=preflight,
            commands=commands_done,
            detail=(
                f"jogs={jog_summary.count} mean={jog_summary.mean_seconds:.3f}s "
                f"p95={jog_summary.p95_seconds:.3f}s max={jog_summary.max_seconds:.3f}s"
            ),
        )
    except Exception as exc:
        log.info("lpc_jog_timing_failed", run_id=run_id, error=str(exc))
        result = LpcJogTimingResult(
            ok=False,
            maintenance_run_id=run_id,
            slot=slot,
            approach_z_mm=approach_z_mm,
            plan=plan,
            preflight=preflight,
            commands=commands_done,
            detail=str(exc),
        )
    finally:
        if run_id is not None:
            try:
                await robot.maintenance_runs.delete(run_id)
            except RobotApiError as exc:
                log.info("lpc_jog_timing_delete_failed", run_id=run_id, error=str(exc))

    timing_dir = robot.settings.ensure_artifact_directory() / "timing"
    timing_path: Path = timing.write(timing_dir)
    result.timing_path = str(timing_path)
    robot.raw_evidence["lpc_jog_timing"] = result.model_dump(mode="json")
    return result
