"""CRS-off Tier B (parameterized GETs) and Tier C (reversible mutations)."""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.catalog import FLEX_HTTP_ENDPOINTS, EndpointSpec, HttpMethod
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    RunStateSnapshot,
    ensure_run_state,
)
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

# robot-server: pre-serialized commands only after a run has ended (not current-idle).
_COMMANDS_PRESERIALIZED_SUFFIX = "/commandsAsPreSerializedList"
_ENDED_RUN_RETRY_ATTEMPTS = 5
_ENDED_RUN_RETRY_DELAY_SECONDS = 0.25

DEFAULT_SMOKE_PROTOCOL = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "test-suggestions"
    / "protocols"
    / "pyro_smoke_no_motion.py"
)

CLIENT_DATA_KEY = "flex-testing-agent-crs-off"
DEFAULT_LOG_IDENTIFIER = "api.log"
TIER_C_OFFSET_URI = "opentrons/opentrons_flex_96_tiprack_50ul/1"
TIER_C_OFFSET_SLOT = "B2"

TIER_B_DESCRIPTOR = CapabilityDescriptor(
    name="crs_off_tier_b",
    description=(
        "Exercise parameterized GET endpoints using protocol/run/data-file/"
        "subsystem/log fixtures (CRS off). Default run presence: current-idle. "
        "Optionally upload fixtures when ALLOW_MUTATIONS=true."
    ),
    risk_level=RiskLevel.READ_ONLY,
    mutates_robot=False,
    evidence_produced=["crs_off_tier_b.json"],
    preconditions=[
        "CRS / accessControlEnabled is false",
        "Desired run state: current-idle (verify or --ensure-run-state)",
    ],
)

TIER_C_DESCRIPTOR = CapabilityDescriptor(
    name="crs_off_tier_c",
    description=(
        "Reversible CRS-off mutations: lights, clientData, camera enable/"
        "stream settings, errorRecovery settings, labwareOffsets "
        "create/search/delete, throwaway protocol/run delete. "
        "Requires ALLOW_MUTATIONS=true. Default run presence: no-current."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    mutates_robot=True,
    requires_cleanup=True,
    evidence_produced=["crs_off_tier_c.json"],
    preconditions=[
        "ALLOW_MUTATIONS=true",
        "CRS / accessControlEnabled is false",
        "Desired run state: no-current",
    ],
)


class ProbeCallResult(BaseModel):
    """One parameterized GET probe outcome."""

    name: str
    method: str
    path: str
    ok: bool
    status_code: int | None = None
    error: str | None = None
    duration_seconds: float | None = None


class TierBResult(BaseModel):
    """CRS-off Tier B summary."""

    fixtures: dict[str, Any] = Field(default_factory=dict)
    created_resources: dict[str, Any] = Field(default_factory=dict)
    run_state: RunStateSnapshot | None = None
    results: list[ProbeCallResult] = Field(default_factory=list)
    ok_count: int = 0
    fail_count: int = 0
    skipped_paths: list[str] = Field(default_factory=list)


class MutationStepResult(BaseModel):
    """One Tier C mutation step."""

    name: str
    ok: bool
    detail: str | None = None


class TierCResult(BaseModel):
    """CRS-off Tier C summary."""

    run_state: RunStateSnapshot | None = None
    steps: list[MutationStepResult] = Field(default_factory=list)
    ok_count: int = 0
    fail_count: int = 0


# Placeholders so Tier B still probes removed / empty resources (expect 404/410).
_PLACEHOLDER_CALIBRATION_ID = "flex-testing-agent-calibration"
_PLACEHOLDER_ANNOTATION_ID = "flex-testing-agent-annotation"
_PLACEHOLDER_UPDATE_SESSION = "flex-testing-agent-update-session"


@dataclass
class _Fixtures:
    protocol_id: str | None = None
    analysis_id: str | None = None
    run_id: str | None = None
    # For commandsAsPreSerializedList (unavailable while a run is still current/active).
    ended_run_id: str | None = None
    data_file_id: str | None = None
    # Run-scoped command (from a seeded / historical run that has commands).
    command_run_id: str | None = None
    command_id: str | None = None
    # Simple PE command store (``GET /commands``), distinct from run commands.
    simple_command_id: str | None = None
    maintenance_run_id: str | None = None
    maintenance_command_id: str | None = None
    command_annotation_id: str | None = None
    calibration_id: str | None = None
    update_session_id: str | None = None
    camera_id: str = "ot_system_camera"
    client_data_key: str | None = None
    log_identifier: str | None = None
    subsystem: str | None = None
    subsystem_update_id: str | None = None
    pipette_id: str | None = None
    username: str | None = None
    created: dict[str, str] = field(default_factory=dict)


async def _ensure_crs_off(robot: FlexRobot) -> None:
    status = await robot.auth_settings.detect_access_control()
    if status.raw_enabled is True:
        raise RuntimeError(
            "CRS / access control is ENABLED; refuse CRS-off suite. "
            f"state={status.state.value}"
        )


async def _gather_fixtures(
    robot: FlexRobot,
    *,
    create_if_missing: bool,
    protocol_path: Path,
    preferred_run_id: str | None = None,
) -> _Fixtures:
    fixtures = _Fixtures()
    protocols = await robot.protocols.list_protocol_summaries()
    if protocols:
        fixtures.protocol_id = str(protocols[0].get("id"))
    elif create_if_missing:
        ensure_mutation_allowed(
            robot.settings,
            risk_level=RiskLevel.REVERSIBLE_MUTATION,
            capability_name="crs_off_tier_b_upload_protocol",
        )
        uploaded = await robot.protocols.upload_protocol(protocol_path)
        protocol_id = robot.protocols.protocol_id_from_upload(uploaded)
        if protocol_id is None:
            raise RuntimeError("Protocol upload succeeded but id missing")
        fixtures.protocol_id = protocol_id
        fixtures.created["protocol_id"] = protocol_id
        robot.raw_evidence["crs_off_protocol_upload"] = uploaded
        log.info("crs_off_uploaded_protocol", protocol_id=protocol_id)

    if fixtures.protocol_id is not None:
        analyses = await robot.protocols.list_analyses(fixtures.protocol_id)
        if analyses:
            fixtures.analysis_id = str(analyses[0].get("id"))

    runs = await robot.runs.list_run_summaries()
    if preferred_run_id is not None:
        fixtures.run_id = preferred_run_id
    elif runs:
        # Prefer a current run when present so path params match run-state setup.
        current = next((r for r in runs if r.get("current") is True), None)
        chosen = current or runs[0]
        fixtures.run_id = str(chosen.get("id"))
    elif create_if_missing and fixtures.protocol_id is not None:
        ensure_mutation_allowed(
            robot.settings,
            risk_level=RiskLevel.REVERSIBLE_MUTATION,
            capability_name="crs_off_tier_b_create_run",
        )
        created = await robot.runs.create_run(protocol_id=fixtures.protocol_id)
        run_id = robot.runs.run_id_from_create(created)
        if run_id is None:
            raise RuntimeError("Run create succeeded but id missing")
        fixtures.run_id = run_id
        fixtures.created["run_id"] = run_id
        robot.raw_evidence["crs_off_run_create"] = created
        log.info("crs_off_created_run", run_id=run_id)

    runs = await robot.runs.list_run_summaries()
    for run in runs:
        if run.get("current") is True:
            continue
        run_id = run.get("id")
        if run_id is not None:
            fixtures.ended_run_id = str(run_id)
            break

    # commandsAsPreSerializedList requires an ended run (robot-server contract).
    if fixtures.ended_run_id is None and create_if_missing:
        fixtures.ended_run_id = await _ensure_ended_run_fixture(robot, fixtures)

    await _gather_command_fixtures(robot, fixtures, create_if_missing=create_if_missing)

    data_files = await robot.data_files.list_data_file_summaries()
    if data_files:
        fixtures.data_file_id = str(data_files[0].get("id"))
    elif create_if_missing:
        ensure_mutation_allowed(
            robot.settings,
            risk_level=RiskLevel.REVERSIBLE_MUTATION,
            capability_name="crs_off_tier_b_upload_csv",
        )
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write("sample,value\nA,1\n")
            csv_path = Path(handle.name)
        try:
            uploaded = await robot.data_files.upload_csv(csv_path)
        finally:
            csv_path.unlink(missing_ok=True)
        file_id = robot.data_files.data_file_id_from_upload(uploaded)
        if file_id is not None:
            fixtures.data_file_id = file_id
            fixtures.created["data_file_id"] = file_id
            robot.raw_evidence["crs_off_data_file_upload"] = uploaded

    await _gather_extra_path_fixtures(
        robot,
        fixtures,
        create_if_missing=create_if_missing,
    )
    return fixtures


async def _first_command_id(robot: FlexRobot, run_id: str) -> str | None:
    commands_payload = await robot.runs.list_commands(run_id)
    commands = commands_payload.get("data")
    if isinstance(commands, list) and commands:
        first = commands[0]
        if isinstance(first, dict) and first.get("id") is not None:
            return str(first["id"])
    return None


async def _first_annotation_id(robot: FlexRobot, run_id: str) -> str | None:
    try:
        annotations = await robot.session.get_json(f"/runs/{run_id}/commandAnnotations")
    except RobotApiError:
        return None
    data = annotations.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        aid = data[0].get("id")
        if aid is not None:
            return str(aid)
    return None


async def _find_run_with_commands(
    robot: FlexRobot,
    runs: list[dict[str, Any]],
    *,
    prefer_annotations: bool = False,
) -> tuple[str, str, str | None] | None:
    """Return ``(run_id, command_id, annotation_id?)`` from seed history.

    Prefers non-current runs. When ``prefer_annotations`` is true, prefer a run
    that already has ``commandAnnotations`` (e.g. ``group_steps`` seed).
    """
    ordered = sorted(runs, key=lambda r: r.get("current") is True)
    fallback: tuple[str, str, str | None] | None = None
    for run in ordered:
        run_id = run.get("id")
        if run_id is None:
            continue
        rid = str(run_id)
        command_id = await _first_command_id(robot, rid)
        if command_id is None:
            continue
        annotation_id = await _first_annotation_id(robot, rid)
        candidate = (rid, command_id, annotation_id)
        if prefer_annotations and annotation_id is not None:
            return candidate
        if fallback is None:
            fallback = candidate
    return fallback


async def _gather_command_fixtures(
    robot: FlexRobot,
    fixtures: _Fixtures,
    *,
    create_if_missing: bool,
) -> None:
    """Fill command / annotation / calibration / update-session path params."""
    # Simple command store (``/commands/{commandId}``), not run-scoped.
    try:
        payload = await robot.session.get_json("/commands")
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            cid = data[0].get("id")
            if cid is not None:
                fixtures.simple_command_id = str(cid)
    except RobotApiError:
        pass

    # Prefer a seeded/historical run that already has commands (current-idle
    # usually has none). Prefer group_steps runs with commandAnnotations.
    if fixtures.command_id is None and fixtures.run_id is not None:
        fixtures.command_id = await _first_command_id(robot, fixtures.run_id)
        if fixtures.command_id is not None:
            fixtures.command_run_id = fixtures.run_id
            fixtures.command_annotation_id = await _first_annotation_id(
                robot, fixtures.run_id
            )

    if fixtures.command_id is None or fixtures.command_annotation_id is None:
        runs = await robot.runs.list_run_summaries()
        found = await _find_run_with_commands(robot, runs, prefer_annotations=True)
        if found is not None:
            rid, cid, aid = found
            use_annotated = fixtures.command_annotation_id is None and aid is not None
            if use_annotated or fixtures.command_id is None:
                fixtures.command_run_id = rid
                fixtures.command_id = cid
                fixtures.command_annotation_id = aid
            log.info(
                "tier_b_command_fixture_from_history",
                command_run_id=fixtures.command_run_id,
                command_id=fixtures.command_id,
                command_annotation_id=fixtures.command_annotation_id,
            )

    if fixtures.command_annotation_id is None and fixtures.command_run_id is not None:
        fixtures.command_annotation_id = await _first_annotation_id(
            robot, fixtures.command_run_id
        )
    if fixtures.command_annotation_id is None:
        fixtures.command_annotation_id = _PLACEHOLDER_ANNOTATION_ID
    if fixtures.simple_command_id is None:
        fixtures.simple_command_id = "flex-testing-agent-simple-command"

    # Flex removed labware calibration CRUD (410); still probe with a placeholder.
    fixtures.calibration_id = _PLACEHOLDER_CALIBRATION_ID
    fixtures.update_session_id = _PLACEHOLDER_UPDATE_SESSION

    # Maintenance run + command (LPC history is deleted; create a tiny fixture).
    try:
        current = await robot.maintenance_runs.get_current()
        data = current.get("data") if isinstance(current, dict) else None
        if isinstance(data, dict) and data.get("id"):
            mid = str(data["id"])
            fixtures.maintenance_run_id = mid
            fixtures.maintenance_command_id = await _first_maintenance_command_id(
                robot, mid
            )
    except RobotApiError:
        pass

    if create_if_missing and fixtures.maintenance_run_id is None:
        ensure_mutation_allowed(
            robot.settings,
            risk_level=RiskLevel.REVERSIBLE_MUTATION,
            capability_name="crs_off_tier_b_maintenance_fixture",
        )
        created = await robot.maintenance_runs.create()
        created_mid = robot.maintenance_runs.run_id_from_create(created)
        if created_mid is None:
            raise RuntimeError("maintenance run create missing id")
        fixtures.maintenance_run_id = created_mid
        fixtures.created["maintenance_run_id"] = created_mid

    if (
        create_if_missing
        and fixtures.maintenance_run_id is not None
        and fixtures.maintenance_command_id is None
    ):
        ensure_mutation_allowed(
            robot.settings,
            risk_level=RiskLevel.REVERSIBLE_MUTATION,
            capability_name="crs_off_tier_b_maintenance_command",
        )
        maint_id = fixtures.maintenance_run_id
        enqueued = await robot.maintenance_runs.enqueue_command(
            maint_id,
            {
                "commandType": "waitForDuration",
                "params": {"seconds": 0},
            },
            wait_until_complete=True,
            timeout_ms=30_000,
            requires_closed_door=False,
        )
        created_cid = robot.maintenance_runs.command_id_from_enqueue(enqueued)
        if created_cid is None:
            created_cid = await _first_maintenance_command_id(robot, maint_id)
        fixtures.maintenance_command_id = created_cid
        if created_cid is not None:
            fixtures.created["maintenance_command_id"] = created_cid

    if fixtures.maintenance_run_id is None:
        fixtures.maintenance_run_id = "flex-testing-agent-maintenance"
    if fixtures.maintenance_command_id is None:
        fixtures.maintenance_command_id = "flex-testing-agent-maint-command"


async def _first_maintenance_command_id(robot: FlexRobot, run_id: str) -> str | None:
    payload = await robot.maintenance_runs.list_commands(run_id)
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        cid = data[0].get("id")
        if cid is not None:
            return str(cid)
    return None


async def _gather_extra_path_fixtures(
    robot: FlexRobot,
    fixtures: _Fixtures,
    *,
    create_if_missing: bool,
) -> None:
    """Fill subsystem / log / clientData / pipette path params."""
    fixtures.log_identifier = DEFAULT_LOG_IDENTIFIER
    fixtures.username = "flex-testing-agent"

    try:
        statuses = await robot.subsystems.list_status()
        if statuses and statuses[0].get("name"):
            fixtures.subsystem = str(statuses[0]["name"])
    except RobotApiError:
        pass

    # Prefer historical updates/all entries when present.
    try:
        all_updates = await robot.session.get_json("/subsystems/updates/all")
        data = all_updates.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            uid = data[0].get("id")
            if uid is not None:
                fixtures.subsystem_update_id = str(uid)
            if fixtures.subsystem is None and data[0].get("subsystem"):
                fixtures.subsystem = str(data[0]["subsystem"])
    except RobotApiError:
        pass

    if fixtures.subsystem_update_id is None:
        try:
            updates = await robot.subsystems.list_current_updates()
            current = updates.get("data") if isinstance(updates, dict) else None
            if isinstance(current, list) and current and isinstance(current[0], dict):
                uid = current[0].get("id")
                if uid is not None:
                    fixtures.subsystem_update_id = str(uid)
        except RobotApiError:
            pass

    try:
        instruments = await robot.session.get_json("/instruments")
        data = instruments.get("data")
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                serial = item.get("serialNumber")
                if serial:
                    fixtures.pipette_id = str(serial)
                    break
    except RobotApiError:
        pass

    if create_if_missing:
        ensure_mutation_allowed(
            robot.settings,
            risk_level=RiskLevel.REVERSIBLE_MUTATION,
            capability_name="crs_off_tier_b_client_data",
        )
        await robot.client_data.put(
            CLIENT_DATA_KEY,
            {"source": "flex-testing-agent", "suite": "crs_off_tier_b"},
        )
        fixtures.client_data_key = CLIENT_DATA_KEY
        fixtures.created["client_data_key"] = CLIENT_DATA_KEY
    else:
        try:
            await robot.client_data.get(CLIENT_DATA_KEY)
            fixtures.client_data_key = CLIENT_DATA_KEY
        except RobotApiError:
            fixtures.client_data_key = None


async def _ensure_ended_run_fixture(
    robot: FlexRobot,
    fixtures: _Fixtures,
) -> str | None:
    """Uncurrent the current idle run, then recreate current-idle for other probes.

    ``GET .../commandsAsPreSerializedList`` is only available after a run has
    ended (see robot-server ``PreSerializedCommandsNotAvailableError``).
    """
    if fixtures.protocol_id is None:
        return None
    ensure_mutation_allowed(
        robot.settings,
        risk_level=RiskLevel.REVERSIBLE_MUTATION,
        capability_name="crs_off_tier_b_ended_run",
    )
    current_id = fixtures.run_id
    if current_id is None:
        return None
    await robot.runs.set_current(current_id, current=False)
    log.info("crs_off_ended_run_for_preserialized", run_id=current_id)
    created = await robot.runs.create_run(protocol_id=fixtures.protocol_id)
    new_id = robot.runs.run_id_from_create(created)
    if new_id is None:
        raise RuntimeError("Recreate current-idle after ending run missing id")
    fixtures.run_id = new_id
    fixtures.created["ended_run_id"] = current_id
    fixtures.created["run_id"] = new_id
    # Commands on the new current idle (usually empty).
    fixtures.command_id = None
    return current_id


def _resolve_path(template: str, fixtures: _Fixtures) -> str | None:
    """Substitute path params; keep runId/commandId pairs from the same resource."""
    if template.startswith("/maintenance_runs/"):
        run_id = fixtures.maintenance_run_id
        command_id = fixtures.maintenance_command_id
    elif template.endswith(_COMMANDS_PRESERIALIZED_SUFFIX):
        run_id = fixtures.ended_run_id
        command_id = fixtures.command_id
    elif template.startswith("/commands/"):
        run_id = fixtures.run_id
        command_id = fixtures.simple_command_id
    elif "{commandId}" in template and template.startswith("/runs/"):
        # Must match the run that owns the command (not current-idle).
        run_id = fixtures.command_run_id or fixtures.run_id
        command_id = fixtures.command_id
    elif "{commandAnnotationId}" in template:
        run_id = fixtures.command_run_id or fixtures.run_id
        command_id = fixtures.command_id
    else:
        run_id = fixtures.run_id
        command_id = fixtures.command_id

    mapping = {
        "protocolId": fixtures.protocol_id,
        "analysisId": fixtures.analysis_id,
        "runId": run_id,
        "commandId": command_id,
        "dataFileId": fixtures.data_file_id,
        "cameraId": fixtures.camera_id,
        "key": fixtures.client_data_key,
        "log_identifier": fixtures.log_identifier,
        "subsystem": fixtures.subsystem,
        "id": fixtures.subsystem_update_id,
        "pipette_id": fixtures.pipette_id,
        "username": fixtures.username,
        "commandAnnotationId": fixtures.command_annotation_id,
        "calibrationId": fixtures.calibration_id,
        "session": fixtures.update_session_id,
    }
    path = template
    for key, value in mapping.items():
        token = "{" + key + "}"
        if token in path:
            if value is None:
                return None
            path = path.replace(token, value)
    if "{" in path:
        return None
    return path


async def _probe_parameterized_get(
    robot: FlexRobot,
    spec: EndpointSpec,
    resolved: str,
) -> ProbeCallResult:
    """GET one parameterized path.

    ``commandsAsPreSerializedList`` may briefly 503 right after a run ends while
    the store settles; retry that case only. Do not soft-accept 503.
    """
    t0 = time.perf_counter()
    retry_preserialized = resolved.endswith(_COMMANDS_PRESERIALIZED_SUFFIX)
    attempts = _ENDED_RUN_RETRY_ATTEMPTS if retry_preserialized else 1
    last_status: int | None = None
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            status_code, _payload = await robot.session.get_with_status(
                resolved,
                timeout=spec.timeout_seconds,
                expected_status=(200, 201, 204, 404),
            )
            return ProbeCallResult(
                name=spec.name,
                method=spec.method.value,
                path=resolved,
                ok=True,
                status_code=status_code,
                duration_seconds=time.perf_counter() - t0,
            )
        except RobotApiError as exc:
            last_status = exc.status_code
            last_error = str(exc)
            if exc.status_code == 503 and retry_preserialized and attempt < attempts:
                log.info(
                    "tier_b_waiting_preserialized_store",
                    path=resolved,
                    attempt=attempt,
                    status_code=503,
                )
                await asyncio.sleep(_ENDED_RUN_RETRY_DELAY_SECONDS)
                continue
            acceptable = exc.status_code is not None and (
                exc.status_code in spec.crs_off_acceptable_status
                or exc.status_code in (200, 404)
            )
            detail = last_error
            if (
                not acceptable
                and exc.status_code == 503
                and "PreSerializedCommandsNotAvailable" in (exc.body or "")
            ):
                detail = (
                    "PreSerializedCommandsNotAvailable: endpoint requires an "
                    "ended run (not current-idle). "
                    f"{last_error}"
                )
            return ProbeCallResult(
                name=spec.name,
                method=spec.method.value,
                path=resolved,
                ok=acceptable,
                status_code=exc.status_code,
                error=None if acceptable else detail,
                duration_seconds=time.perf_counter() - t0,
            )

    return ProbeCallResult(
        name=spec.name,
        method=spec.method.value,
        path=resolved,
        ok=False,
        status_code=last_status,
        error=last_error or f"exhausted retries for {resolved}",
        duration_seconds=time.perf_counter() - t0,
    )


async def run_crs_off_tier_b(
    robot: FlexRobot,
    *,
    create_fixtures: bool = False,
    protocol_path: Path | None = None,
    run_state: DesiredRunState = DesiredRunState.CURRENT_IDLE,
    ensure_run_state_flag: bool = False,
) -> TierBResult:
    """Probe parameterized catalog GETs using available fixtures.

    Default run presence is ``current-idle`` so run-scoped GETs and camera
    run-active behavior are exercised against a known state (see crs-testing.md).
    """
    await _ensure_crs_off(robot)
    smoke = protocol_path or DEFAULT_SMOKE_PROTOCOL

    # Upload protocol first when needed so CURRENT_IDLE ensure can create a run.
    if create_fixtures:
        protocols = await robot.protocols.list_protocol_summaries()
        if not protocols:
            ensure_mutation_allowed(
                robot.settings,
                risk_level=RiskLevel.REVERSIBLE_MUTATION,
                capability_name="crs_off_tier_b_upload_protocol",
            )
            uploaded = await robot.protocols.upload_protocol(smoke)
            protocol_id = robot.protocols.protocol_id_from_upload(uploaded)
            if protocol_id is None:
                raise RuntimeError("Protocol upload succeeded but id missing")
            robot.raw_evidence["crs_off_protocol_upload"] = uploaded
            log.info("crs_off_uploaded_protocol", protocol_id=protocol_id)

    protocols = await robot.protocols.list_protocol_summaries()
    protocol_id = str(protocols[0]["id"]) if protocols else None
    snap = await ensure_run_state(
        robot,
        run_state,
        ensure=ensure_run_state_flag or create_fixtures,
        protocol_id=protocol_id,
        capability_name="crs_off_tier_b_run_state",
    )

    fixtures = await _gather_fixtures(
        robot,
        create_if_missing=create_fixtures,
        protocol_path=smoke,
        preferred_run_id=snap.current_run_id,
    )

    results: list[ProbeCallResult] = []
    skipped: list[str] = []
    for spec in FLEX_HTTP_ENDPOINTS:
        if spec.method != HttpMethod.GET or not spec.parameterized or spec.blocked:
            continue
        if "redoc" in spec.path:
            continue
        resolved = _resolve_path(spec.path, fixtures)
        if resolved is None:
            skipped.append(spec.path)
            continue
        results.append(await _probe_parameterized_get(robot, spec, resolved))

    # Drop throwaway maintenance fixture so later seeds/suites are not blocked.
    created_maint = fixtures.created.get("maintenance_run_id")
    if created_maint:
        with contextlib.suppress(Exception):
            await robot.maintenance_runs.delete(created_maint)

    summary = TierBResult(
        fixtures={
            "protocol_id": fixtures.protocol_id,
            "analysis_id": fixtures.analysis_id,
            "run_id": fixtures.run_id,
            "ended_run_id": fixtures.ended_run_id,
            "data_file_id": fixtures.data_file_id,
            "command_run_id": fixtures.command_run_id,
            "command_id": fixtures.command_id,
            "simple_command_id": fixtures.simple_command_id,
            "maintenance_run_id": fixtures.maintenance_run_id,
            "maintenance_command_id": fixtures.maintenance_command_id,
            "command_annotation_id": fixtures.command_annotation_id,
            "calibration_id": fixtures.calibration_id,
            "update_session_id": fixtures.update_session_id,
            "camera_id": fixtures.camera_id,
            "client_data_key": fixtures.client_data_key,
            "log_identifier": fixtures.log_identifier,
            "subsystem": fixtures.subsystem,
            "subsystem_update_id": fixtures.subsystem_update_id,
            "pipette_id": fixtures.pipette_id,
            "username": fixtures.username,
        },
        created_resources=dict(fixtures.created),
        run_state=snap,
        results=results,
        ok_count=sum(1 for r in results if r.ok),
        fail_count=sum(1 for r in results if not r.ok),
        skipped_paths=skipped,
    )
    robot.raw_evidence["crs_off_tier_b"] = summary.model_dump(mode="json")
    return summary


async def _tier_c_step(
    steps: list[MutationStepResult],
    name: str,
    coro: Awaitable[str],
) -> None:
    try:
        detail = await coro
        steps.append(MutationStepResult(name=name, ok=True, detail=detail))
    except Exception as exc:
        steps.append(MutationStepResult(name=name, ok=False, detail=str(exc)))


async def _wait_protocol_analysis(
    robot: FlexRobot,
    protocol_id: str,
    *,
    timeout_seconds: float = 120.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        analyses = await robot.protocols.list_analyses(protocol_id)
        if analyses:
            status = str(analyses[0].get("status") or "")
            if status in {"completed", "succeeded"}:
                return
            if status in {"not-ok", "failed", "error"}:
                raise RuntimeError(f"Analysis failed for {protocol_id}: {analyses[0]}")
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for analysis of {protocol_id}")


async def run_crs_off_tier_c(
    robot: FlexRobot,
    *,
    run_state: DesiredRunState = DesiredRunState.NO_CURRENT,
    ensure_run_state_flag: bool = True,
) -> TierCResult:
    """Run reversible CRS-off mutations with cleanup.

    Defaults to ``no-current`` so lights / clientData are not confounded by an
    active protocol-run process (see crs-testing.md run-state matrix).
    """
    ensure_mutation_allowed(
        robot.settings,
        risk_level=TIER_C_DESCRIPTOR.risk_level,
        capability_name=TIER_C_DESCRIPTOR.name,
    )
    await _ensure_crs_off(robot)
    snap = await ensure_run_state(
        robot,
        run_state,
        ensure=ensure_run_state_flag,
        capability_name="crs_off_tier_c_run_state",
    )

    steps: list[MutationStepResult] = []

    async def _lights() -> str:
        before = await robot.robot_control.get_lights()
        on_before = bool(before.get("on"))
        flipped = await robot.robot_control.set_lights(on=not on_before)
        restored = await robot.robot_control.set_lights(on=on_before)
        if bool(restored.get("on")) != on_before:
            raise RuntimeError(
                f"lights restore mismatch before={on_before} "
                f"flipped={flipped.get('on')} restored={restored.get('on')}"
            )
        return f"before={on_before} restored={restored.get('on')}"

    async def _client_data() -> str:
        payload = {"source": "flex-testing-agent", "suite": "crs_off_tier_c"}
        put = await robot.client_data.put(CLIENT_DATA_KEY, payload)
        got = await robot.client_data.get(CLIENT_DATA_KEY)
        await robot.client_data.delete(CLIENT_DATA_KEY)
        return f"put_keys={list(put.keys())} get_ok={bool(got)}"

    async def _camera_enable_restore() -> str:
        before = await robot.camera.get_camera()
        enabled_before = bool(before.get("cameraEnabled"))
        await robot.camera.set_camera_enabled(camera_enabled=not enabled_before)
        restored = await robot.camera.set_camera_enabled(camera_enabled=enabled_before)
        if bool(restored.get("cameraEnabled")) != enabled_before:
            raise RuntimeError(f"camera enable restore failed: {restored}")
        return f"enabled_before={enabled_before}"

    async def _camera_stream_settings_restore() -> str:
        before = await robot.camera.get_stream_settings()
        # Live response is a flat settings object (not always JSON-API wrapped).
        settings = dict(before)
        if "data" in settings and isinstance(settings["data"], dict):
            settings = dict(settings["data"])
        # Normalize quoted source strings seen on some builds.
        source = settings.get("source")
        if isinstance(source, str) and source.startswith('"'):
            settings["source"] = source.strip('"')
        await robot.camera.set_stream_settings(settings)
        return f"source={settings.get('source')} fps={settings.get('framerate')}"

    async def _error_recovery_restore() -> str:
        before = await robot.error_recovery.get_settings()
        enabled_before = robot.error_recovery.enabled_from_payload(before)
        if enabled_before is None:
            raise RuntimeError(f"errorRecovery settings missing enabled: {before}")
        await robot.error_recovery.set_enabled(enabled=not enabled_before)
        restored = await robot.error_recovery.set_enabled(enabled=enabled_before)
        enabled_after = robot.error_recovery.enabled_from_payload(restored)
        if enabled_after != enabled_before:
            raise RuntimeError(f"errorRecovery restore failed: {restored}")
        return f"enabled_before={enabled_before}"

    async def _labware_offsets_roundtrip() -> str:
        offset_id: str | None = None
        try:
            created = await robot.labware_offsets.create_offset(
                {
                    "definitionUri": TIER_C_OFFSET_URI,
                    "locationSequence": [
                        {
                            "kind": "onAddressableArea",
                            "addressableAreaName": TIER_C_OFFSET_SLOT,
                        }
                    ],
                    "vector": {"x": 0.01, "y": 0.02, "z": 0.03},
                }
            )
            offset_id = robot.labware_offsets.offset_id_from_create(created)
            if offset_id is None:
                raise RuntimeError("labwareOffsets create missing id")
            searched = await robot.labware_offsets.search(
                {
                    "data": {
                        "filters": [
                            {
                                "definitionUri": TIER_C_OFFSET_URI,
                                "locationSequence": [
                                    {
                                        "kind": "onAddressableArea",
                                        "addressableAreaName": TIER_C_OFFSET_SLOT,
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
            return f"offset_id={offset_id} search_keys={list(searched.keys())}"
        finally:
            if offset_id is not None:
                with contextlib.suppress(Exception):
                    await robot.labware_offsets.delete_one(offset_id)

    async def _protocol_run_delete() -> str:
        uploaded = await robot.protocols.upload_protocol(DEFAULT_SMOKE_PROTOCOL)
        protocol_id = robot.protocols.protocol_id_from_upload(uploaded)
        if protocol_id is None:
            raise RuntimeError("tier-c cleanup protocol upload missing id")
        await _wait_protocol_analysis(robot, protocol_id)
        created = await robot.runs.create_run(protocol_id=protocol_id)
        run_id = robot.runs.run_id_from_create(created)
        if run_id is None:
            raise RuntimeError("tier-c cleanup run create missing id")
        await robot.runs.set_current(run_id, current=False)
        await robot.runs.delete_run(run_id)
        await robot.protocols.delete_protocol(protocol_id)
        return f"deleted protocol={protocol_id[:8]} run={run_id[:8]}"

    await _tier_c_step(steps, "lights_toggle_restore", _lights())
    await _tier_c_step(steps, "client_data_put_get_delete", _client_data())
    await _tier_c_step(steps, "camera_enable_restore", _camera_enable_restore())
    await _tier_c_step(
        steps, "camera_stream_settings_restore", _camera_stream_settings_restore()
    )
    await _tier_c_step(steps, "error_recovery_restore", _error_recovery_restore())
    await _tier_c_step(steps, "labware_offsets_roundtrip", _labware_offsets_roundtrip())
    await _tier_c_step(steps, "protocol_run_delete", _protocol_run_delete())

    # Best-effort cleanup if clientData step failed mid-way.
    with contextlib.suppress(Exception):
        await robot.client_data.delete(CLIENT_DATA_KEY)

    summary = TierCResult(
        run_state=snap,
        steps=steps,
        ok_count=sum(1 for s in steps if s.ok),
        fail_count=sum(1 for s in steps if not s.ok),
    )
    robot.raw_evidence["crs_off_tier_c"] = summary.model_dump(mode="json")
    return summary
