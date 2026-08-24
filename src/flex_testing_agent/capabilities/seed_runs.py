"""Seed a diverse protocol-run history with live motion (explicit operator request).

See ``docs/known-state-and-latency.md``. Requires clear deck, trash A3, HS D1,
and ``ALLOW_MUTATIONS=true``. Applies Kansas deck configuration before each
seed so scenarios do not depend on leftover deck config. Disables
stall/overpressure sensing; updates subsystem FW when needed after OS changes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.capabilities.known_state import apply_kansas_deck_configuration
from flex_testing_agent.clients.camera import CameraClient
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.robot_settings import (
    DISABLE_OVERPRESSURE_DETECTION,
    DISABLE_STALL_DETECTION,
    RobotSettingsClient,
)
from flex_testing_agent.clients.subsystems import SubsystemsClient
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    ensure_run_state,
    release_current_run,
)
from flex_testing_agent.orchestration.timing import TimingSession
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

PROTOCOLS_DIR = (
    Path(__file__).resolve().parents[3] / "docs" / "test-suggestions" / "protocols"
)

SEED_RUNS_DESCRIPTOR = CapabilityDescriptor(
    name="seed_runs",
    description=(
        "Upload/analyze/play seed protocols (and scripted LPC) to build known "
        "run history with real motion (dry deck). PHYSICAL_MOTION; "
        "operator-requested only."
    ),
    risk_level=RiskLevel.PHYSICAL_MOTION,
    mutates_robot=True,
    max_execution_time_seconds=3600.0,
    evidence_produced=["seed_runs.json", "timing"],
    preconditions=[
        "ALLOW_MUTATIONS=true",
        "Operator explicitly requested live motion / seed-runs",
        "Deck clear except trash A3 and heater-shaker D1 (config applied per seed)",
        "Free slot C2 for lpc_scripted virtual tiprack",
        "CRS on: ROBOT_USERNAME / ROBOT_PASSWORD (OAuth + protocol-log signoff)",
    ],
)

SEED_SIGNOFF_LABEL = "flex-testing-agent seed-runs"


def seed_signoff_label(robot: FlexRobot) -> str | None:
    """Return a protocol-log signoff label when the session is OAuth-backed."""
    if robot.session.access_token is None:
        return None
    notes = robot.settings.robot_user_notes
    if notes is not None and not notes.strip():
        return SEED_SIGNOFF_LABEL
    return notes or SEED_SIGNOFF_LABEL


class SeedId(StrEnum):
    SIMPLE_HOME_MOVE = "simple_home_move"
    COMPLEX_TRANSFER_DRY = "complex_transfer_dry"
    HEATER_SHAKER_BRIEF = "heater_shaker_brief"
    CANCEL_MID_RUN = "cancel_mid_run"
    CAMERA_AND_COMMENTS = "camera_and_comments"
    FAILED_INTENTIONAL = "failed_intentional"
    IDLE_CURRENT = "idle_current"
    PAUSE_MID_RUN = "pause_mid_run"
    LPC_SCRIPTED = "lpc_scripted"


@dataclass(frozen=True)
class SeedSpec:
    seed_id: SeedId
    protocol_file: str
    play: bool
    cancel_after_start: bool = False
    pause_after_start: bool = False
    leave_current: bool = False
    capture_camera: bool = False
    expected_terminal: tuple[str, ...] = ("succeeded",)


SEED_SPECS: tuple[SeedSpec, ...] = (
    SeedSpec(
        SeedId.SIMPLE_HOME_MOVE,
        "seed_simple_home_move.py",
        play=True,
        expected_terminal=("succeeded",),
    ),
    SeedSpec(
        SeedId.COMPLEX_TRANSFER_DRY,
        "seed_complex_dry_moves.py",
        play=True,
        expected_terminal=("succeeded",),
    ),
    SeedSpec(
        SeedId.HEATER_SHAKER_BRIEF,
        "seed_heater_shaker_brief.py",
        play=True,
        expected_terminal=("succeeded",),
    ),
    SeedSpec(
        SeedId.CANCEL_MID_RUN,
        "seed_cancel_mid_run.py",
        play=True,
        cancel_after_start=True,
        expected_terminal=("stopped",),
    ),
    SeedSpec(
        SeedId.CAMERA_AND_COMMENTS,
        "seed_camera_and_comments.py",
        play=True,
        capture_camera=True,
        expected_terminal=("succeeded",),
    ),
    SeedSpec(
        SeedId.FAILED_INTENTIONAL,
        "seed_failed_intentional.py",
        play=True,
        expected_terminal=("failed",),
    ),
    SeedSpec(
        SeedId.PAUSE_MID_RUN,
        "seed_pause_mid_run.py",
        play=True,
        pause_after_start=True,
        # Uncurrent after pause so idle_current can become the current fixture.
        leave_current=False,
        expected_terminal=("paused",),
    ),
    SeedSpec(
        SeedId.IDLE_CURRENT,
        "seed_idle_current.py",
        play=False,
        leave_current=True,
        expected_terminal=("idle",),
    ),
)

# Ordered inventory; ``lpc_scripted`` is HTTP maintenance-run driven (no .py).
ALL_SEED_IDS: tuple[SeedId, ...] = (
    *(s.seed_id for s in SEED_SPECS),
    SeedId.LPC_SCRIPTED,
)


class SeedOutcome(BaseModel):
    """One seed scenario result."""

    seed_id: str
    ok: bool
    protocol_id: str | None = None
    run_id: str | None = None
    final_status: str | None = None
    detail: str | None = None
    camera_path: str | None = None
    camera_error: str | None = None
    timings: dict[str, float] = Field(default_factory=dict)


class SeedRunsResult(BaseModel):
    """Full seed-runs suite summary."""

    preflight: dict[str, Any] = Field(default_factory=dict)
    outcomes: list[SeedOutcome] = Field(default_factory=list)
    timing_path: str | None = None
    ok_count: int = 0
    fail_count: int = 0


async def _wait_analysis(
    robot: FlexRobot,
    protocol_id: str,
    *,
    timeout_seconds: float = 180.0,
) -> str | None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        analyses = await robot.protocols.list_analyses(protocol_id)
        if analyses:
            latest = analyses[0]
            status = str(latest.get("status") or "")
            analysis_id = latest.get("id")
            if status in {"completed", "succeeded"} and analysis_id is not None:
                return str(analysis_id)
            if status in {"not-ok", "failed", "error"}:
                raise RuntimeError(f"Analysis failed for {protocol_id}: {latest}")
        await asyncio.sleep(1.0)
    raise TimeoutError(f"Timed out waiting for analysis of {protocol_id}")


async def _wait_run_status(
    robot: FlexRobot,
    run_id: str,
    *,
    wanted: set[str],
    timeout_seconds: float = 600.0,
    poll_interval: float = 0.5,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last = "unknown"
    while asyncio.get_running_loop().time() < deadline:
        payload = await robot.runs.get_run(run_id)
        status = robot.runs.status_from_run(payload) or "unknown"
        last = status
        if status in wanted:
            return status
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"Timed out waiting for run {run_id} in {wanted}; last={last}")


async def _wait_first_command_activity(
    robot: FlexRobot,
    run_id: str,
    *,
    timeout_seconds: float = 120.0,
) -> None:
    """Wait until run is running or at least one command exists."""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        payload = await robot.runs.get_run(run_id)
        status = robot.runs.status_from_run(payload) or ""
        if status in {"running", "succeeded", "stopped", "failed"}:
            return
        commands = await robot.runs.list_commands(run_id)
        data = commands.get("data")
        if isinstance(data, list) and data:
            return
        await asyncio.sleep(0.25)


async def _preflight(
    robot: FlexRobot,
    timing: TimingSession,
    *,
    update_firmware: bool,
) -> dict[str, Any]:
    info: dict[str, Any] = {}
    settings_client = RobotSettingsClient(robot.session)
    async with timing.aspan("preflight.disable_sensing"):
        for setting_id in (
            DISABLE_STALL_DETECTION,
            DISABLE_OVERPRESSURE_DETECTION,
        ):
            await settings_client.set_setting(setting_id, True)
            info[setting_id] = True

    # reset-data / factory defaults leave the camera off; captureImage needs it.
    camera = CameraClient(robot.session)
    async with timing.aspan("preflight.enable_camera"):
        status = await camera.get_camera()
        enabled = bool(status.get("cameraEnabled"))
        if not enabled:
            status = await camera.set_camera_enabled(camera_enabled=True)
        info["cameraEnabled"] = bool(status.get("cameraEnabled", True))

    subsystems = SubsystemsClient(robot.session)
    needing = await subsystems.subsystems_needing_update()
    in_flight = await subsystems.current_update_summaries()
    info["fw_update_needed"] = needing
    info["fw_updates_in_flight"] = in_flight
    # Always drain in-flight updates (e.g. leftover from install) before motion.
    if update_firmware and needing:
        async with timing.aspan("preflight.subsystem_fw", meta={"subsystems": needing}):
            for name in needing:
                log.info("starting_subsystem_update", subsystem=name)
                try:
                    started = await subsystems.start_update(name)
                    log.info("subsystem_update_started", subsystem=name, body=started)
                except RobotApiError as exc:
                    # Concurrent updates may 409; keep going and wait for idle.
                    log.info(
                        "subsystem_update_start_failed",
                        subsystem=name,
                        error=str(exc),
                    )
            await subsystems.wait_until_firmware_idle(timeout_seconds=1200.0)
        info["fw_update_completed"] = True
    elif needing or in_flight:
        async with timing.aspan("preflight.wait_fw_idle"):
            await subsystems.wait_until_firmware_idle(timeout_seconds=1200.0)
        info["fw_update_waited"] = True
    return info


async def _prepare_seed(
    robot: FlexRobot,
    timing: TimingSession,
    *,
    seed_id: str,
) -> str:
    """Clear current run (if any) and apply Kansas deck config for this seed."""
    await ensure_run_state(
        robot,
        DesiredRunState.NO_CURRENT,
        ensure=True,
        capability_name="seed_runs",
        signed_by=seed_signoff_label(robot),
    )
    return await apply_kansas_deck_configuration(
        robot,
        timing=timing,
        span_name=f"seed.{seed_id}.deck",
    )


async def _run_one_seed(
    robot: FlexRobot,
    spec: SeedSpec,
    timing: TimingSession,
    *,
    picture_dir: Path,
) -> SeedOutcome:
    protocol_path = PROTOCOLS_DIR / spec.protocol_file
    if not protocol_path.is_file():
        return SeedOutcome(
            seed_id=spec.seed_id.value,
            ok=False,
            detail=f"missing protocol file {protocol_path}",
        )

    local_timings: dict[str, float] = {}
    prefix = f"seed.{spec.seed_id.value}"

    timing.start(f"{prefix}.upload")
    uploaded = await robot.protocols.upload_protocol(protocol_path)
    protocol_id = robot.protocols.protocol_id_from_upload(uploaded)
    timing.stop(f"{prefix}.upload")
    span = timing.spans[-1]
    if span.duration_seconds is not None:
        local_timings["protocol.upload"] = span.duration_seconds
    if protocol_id is None:
        return SeedOutcome(
            seed_id=spec.seed_id.value,
            ok=False,
            detail="protocol upload missing id",
        )

    timing.start(f"{prefix}.analyze")
    analysis_id = await _wait_analysis(robot, protocol_id)
    timing.stop(f"{prefix}.analyze")
    span = timing.spans[-1]
    if span.duration_seconds is not None:
        local_timings["protocol.analyze"] = span.duration_seconds

    timing.start(f"{prefix}.create")
    created = await robot.runs.create_run(protocol_id=protocol_id, timeout=120.0)
    run_id = robot.runs.run_id_from_create(created)
    timing.stop(f"{prefix}.create")
    span = timing.spans[-1]
    if span.duration_seconds is not None:
        local_timings["run.create"] = span.duration_seconds
    if run_id is None:
        return SeedOutcome(
            seed_id=spec.seed_id.value,
            ok=False,
            protocol_id=protocol_id,
            detail="run create missing id",
        )

    camera_path: str | None = None
    camera_error: str | None = None
    final_status = robot.runs.status_from_run(created)

    if not spec.play:
        ok = final_status in spec.expected_terminal or final_status == "idle"
        return SeedOutcome(
            seed_id=spec.seed_id.value,
            ok=ok,
            protocol_id=protocol_id,
            run_id=run_id,
            final_status=final_status,
            detail=f"analysis={analysis_id}; left current idle (no play)",
            timings=local_timings,
        )

    timing.start(f"{prefix}.play_to_running")
    await robot.runs.play(run_id)
    try:
        await _wait_run_status(
            robot,
            run_id,
            wanted={"running", "succeeded", "stopped", "failed"},
            timeout_seconds=180.0,
        )
    finally:
        timing.stop(f"{prefix}.play_to_running")
    span = timing.spans[-1]
    if span.duration_seconds is not None:
        local_timings["run.play_to_running"] = span.duration_seconds

    timing.start(f"{prefix}.play_to_first_command")
    await _wait_first_command_activity(robot, run_id)
    timing.stop(f"{prefix}.play_to_first_command")
    span = timing.spans[-1]
    if span.duration_seconds is not None:
        local_timings["run.play_to_first_command"] = span.duration_seconds

    if spec.capture_camera:
        pic = picture_dir / f"{spec.seed_id.value}.jpg"
        camera = CameraClient(robot.session)
        try:
            async with timing.aspan(f"{prefix}.camera"):
                # Prefer picture; preview often 422 while run is current.
                content = await camera.take_picture(timeout=60.0)
                pic.parent.mkdir(parents=True, exist_ok=True)
                pic.write_bytes(content)
                camera_path = str(pic)
        except Exception as exc:
            camera_error = str(exc)
            try:
                content = await camera.capture_preview_image(timeout=60.0)
                pic.parent.mkdir(parents=True, exist_ok=True)
                pic.write_bytes(content)
                camera_path = str(pic)
                camera_error = f"picture failed ({exc}); preview ok"
            except Exception as exc2:
                camera_error = f"picture={exc}; preview={exc2}"

    pause_ok: bool | None = None
    if spec.cancel_after_start:
        timing.start(f"{prefix}.cancel")
        await robot.runs.stop(run_id)
        final_status = await _wait_run_status(
            robot,
            run_id,
            wanted={"stopped", "failed", "succeeded"},
            timeout_seconds=180.0,
        )
        timing.stop(f"{prefix}.cancel")
        span = timing.spans[-1]
        if span.duration_seconds is not None:
            local_timings["run.cancel_latency"] = span.duration_seconds
    elif spec.pause_after_start:
        timing.start(f"{prefix}.pause")
        await robot.runs.pause(run_id)
        final_status = await _wait_run_status(
            robot,
            run_id,
            wanted={"paused", "stopped", "failed", "succeeded"},
            timeout_seconds=180.0,
        )
        timing.stop(f"{prefix}.pause")
        span = timing.spans[-1]
        if span.duration_seconds is not None:
            local_timings["run.pause_latency"] = span.duration_seconds
        # Paused runs cannot be uncurrented (409). Stop to free current unless
        # this seed intentionally leaves a current paused fixture.
        if not spec.leave_current and final_status == "paused":
            timing.start(f"{prefix}.stop_after_pause")
            await robot.runs.stop(run_id)
            final_status = await _wait_run_status(
                robot,
                run_id,
                wanted={"stopped", "failed", "succeeded"},
                timeout_seconds=180.0,
            )
            timing.stop(f"{prefix}.stop_after_pause")
            span = timing.spans[-1]
            if span.duration_seconds is not None:
                local_timings["run.stop_after_pause"] = span.duration_seconds
            pause_ok = True
        else:
            pause_ok = final_status in spec.expected_terminal
    else:
        final_status = await _wait_run_status(
            robot,
            run_id,
            wanted={"succeeded", "stopped", "failed"},
            timeout_seconds=900.0,
        )

    if pause_ok is not None:
        ok = pause_ok
        detail = (
            None if ok else f"expected {spec.expected_terminal}, got {final_status}"
        )
        if ok and not spec.leave_current and final_status == "stopped":
            detail = "paused then stopped to free current run"
    else:
        ok = final_status in spec.expected_terminal
        detail = (
            None if ok else f"expected {spec.expected_terminal}, got {final_status}"
        )

    # Uncurrent finished runs so the next seed can become current, unless the
    # seed is meant to leave a current fixture (idle / paused). CRS-on needs
    # protocol-log signoff before PATCH current=false.
    if not spec.leave_current:
        try:
            await release_current_run(
                robot, run_id, signed_by=seed_signoff_label(robot)
            )
        except RobotApiError as exc:
            log.info("uncurrent_after_seed_failed", run_id=run_id, error=str(exc))

    return SeedOutcome(
        seed_id=spec.seed_id.value,
        ok=ok,
        protocol_id=protocol_id,
        run_id=run_id,
        final_status=final_status,
        detail=detail,
        camera_path=camera_path,
        camera_error=camera_error,
        timings=local_timings,
    )


async def _run_lpc_seed(
    robot: FlexRobot,
    timing: TimingSession,
) -> SeedOutcome:
    """Scripted LPC via maintenance_runs + persisted /labwareOffsets."""
    from flex_testing_agent.capabilities.seed_lpc import run_seed_lpc_scripted

    result = await run_seed_lpc_scripted(robot, timing)
    return SeedOutcome(
        seed_id=SeedId.LPC_SCRIPTED.value,
        ok=result.ok,
        run_id=result.maintenance_run_id,
        final_status="offset_stored" if result.ok else "failed",
        detail=result.detail
        if result.detail
        else (f"offset_id={result.offset_id}; commands={len(result.commands)}"),
        timings=result.timings,
    )


async def run_seed_runs(
    robot: FlexRobot,
    *,
    seed_ids: list[SeedId] | None = None,
    update_firmware: bool = True,
    strict: bool = False,
) -> SeedRunsResult:
    """Execute seed scenarios (motion). Caller must have requested live play."""
    ensure_mutation_allowed(
        robot.settings,
        risk_level=SEED_RUNS_DESCRIPTOR.risk_level,
        capability_name=SEED_RUNS_DESCRIPTOR.name,
    )

    timing = TimingSession(
        label="seed-runs",
        robot_host=robot.settings.robot_host,
    )
    try:
        health = await robot.verify_health()
        timing.system_version = health.system_version
        timing.api_version = health.api_version
    except Exception as exc:
        timing.note(f"health: {exc}")

    await ensure_run_state(
        robot,
        DesiredRunState.NO_CURRENT,
        ensure=True,
        capability_name="seed_runs",
        signed_by=seed_signoff_label(robot),
    )

    selected = set(ALL_SEED_IDS)
    if seed_ids is not None:
        selected = set(seed_ids)
    specs = [s for s in SEED_SPECS if s.seed_id in selected]
    run_lpc = SeedId.LPC_SCRIPTED in selected

    preflight = await _preflight(robot, timing, update_firmware=update_firmware)
    robot.raw_evidence["seed_preflight"] = preflight

    picture_dir = robot.settings.ensure_artifact_directory() / "camera" / "seed-runs"
    outcomes: list[SeedOutcome] = []
    stopped_early = False
    for spec in specs:
        log.info("seed_start", seed_id=spec.seed_id.value)
        try:
            await _prepare_seed(robot, timing, seed_id=spec.seed_id.value)
            outcome = await _run_one_seed(robot, spec, timing, picture_dir=picture_dir)
        except Exception as exc:
            outcome = SeedOutcome(
                seed_id=spec.seed_id.value,
                ok=False,
                detail=str(exc),
            )
            log.info("seed_failed", seed_id=spec.seed_id.value, error=str(exc))
        outcomes.append(outcome)
        robot.raw_evidence[f"seed_{spec.seed_id.value}"] = outcome.model_dump(
            mode="json"
        )
        if strict and not outcome.ok:
            stopped_early = True
            break

    if run_lpc and not stopped_early:
        log.info("seed_start", seed_id=SeedId.LPC_SCRIPTED.value)
        try:
            await _prepare_seed(robot, timing, seed_id=SeedId.LPC_SCRIPTED.value)
            outcome = await _run_lpc_seed(robot, timing)
        except Exception as exc:
            outcome = SeedOutcome(
                seed_id=SeedId.LPC_SCRIPTED.value,
                ok=False,
                detail=str(exc),
            )
            log.info(
                "seed_failed",
                seed_id=SeedId.LPC_SCRIPTED.value,
                error=str(exc),
            )
        outcomes.append(outcome)
        robot.raw_evidence[f"seed_{SeedId.LPC_SCRIPTED.value}"] = outcome.model_dump(
            mode="json"
        )

    path = timing.write(robot.settings.ensure_artifact_directory() / "timing")
    result = SeedRunsResult(
        preflight=preflight,
        outcomes=outcomes,
        timing_path=str(path),
        ok_count=sum(1 for o in outcomes if o.ok),
        fail_count=sum(1 for o in outcomes if not o.ok),
    )
    robot.raw_evidence["seed_runs"] = result.model_dump(mode="json")
    return result


def parse_seed_ids(values: list[str] | None) -> list[SeedId] | None:
    """Parse CLI seed id strings; None means all."""
    if not values:
        return None
    parsed: list[SeedId] = []
    for raw in values:
        key = raw.strip().lower().replace("-", "_")
        try:
            parsed.append(SeedId(key))
        except ValueError as exc:
            allowed = ", ".join(s.value for s in SeedId)
            raise ValueError(
                f"Unknown seed id {raw!r}; expected one of: {allowed}"
            ) from exc
    return parsed
