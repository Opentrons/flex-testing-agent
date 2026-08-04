"""CRS-off Tier B (parameterized GETs) and Tier C (reversible mutations)."""

from __future__ import annotations

import contextlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.catalog import FLEX_HTTP_ENDPOINTS, HttpMethod
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

DEFAULT_SMOKE_PROTOCOL = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "test-suggestions"
    / "protocols"
    / "pyro_smoke_no_motion.py"
)

CLIENT_DATA_KEY = "flex-testing-agent-crs-off"

TIER_B_DESCRIPTOR = CapabilityDescriptor(
    name="crs_off_tier_b",
    description=(
        "Exercise parameterized GET endpoints using protocol/run/data-file "
        "fixtures (CRS off). Default run presence: current-idle. Optionally "
        "upload a smoke protocol and create a run when ALLOW_MUTATIONS=true."
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
        "Reversible CRS-off mutations: lights toggle (restored) and clientData "
        "put/get/delete. Requires ALLOW_MUTATIONS=true. Default run presence: "
        "no-current."
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


@dataclass
class _Fixtures:
    protocol_id: str | None = None
    analysis_id: str | None = None
    run_id: str | None = None
    data_file_id: str | None = None
    command_id: str | None = None
    camera_id: str = "ot_system_camera"
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

    if fixtures.run_id is not None:
        commands_payload = await robot.runs.list_commands(fixtures.run_id)
        commands = commands_payload.get("data")
        if isinstance(commands, list) and commands:
            first = commands[0]
            if isinstance(first, dict) and first.get("id") is not None:
                fixtures.command_id = str(first["id"])

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

    return fixtures


def _resolve_path(template: str, fixtures: _Fixtures) -> str | None:
    mapping = {
        "protocolId": fixtures.protocol_id,
        "analysisId": fixtures.analysis_id,
        "runId": fixtures.run_id,
        "commandId": fixtures.command_id,
        "dataFileId": fixtures.data_file_id,
        "cameraId": fixtures.camera_id,
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
        try:
            status_code, _payload = await robot.session.get_with_status(
                resolved,
                timeout=spec.timeout_seconds,
                expected_status=(200, 201, 204, 404),
            )
            results.append(
                ProbeCallResult(
                    name=spec.name,
                    method=spec.method.value,
                    path=resolved,
                    ok=True,
                    status_code=status_code,
                )
            )
        except RobotApiError as exc:
            acceptable = exc.status_code is not None and (
                exc.status_code in spec.crs_off_acceptable_status
                or exc.status_code in (200, 404)
            )
            results.append(
                ProbeCallResult(
                    name=spec.name,
                    method=spec.method.value,
                    path=resolved,
                    ok=acceptable,
                    status_code=exc.status_code,
                    error=None if acceptable else str(exc),
                )
            )

    summary = TierBResult(
        fixtures={
            "protocol_id": fixtures.protocol_id,
            "analysis_id": fixtures.analysis_id,
            "run_id": fixtures.run_id,
            "data_file_id": fixtures.data_file_id,
            "command_id": fixtures.command_id,
            "camera_id": fixtures.camera_id,
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

    # Lights: capture, flip, restore.
    try:
        before = await robot.robot_control.get_lights()
        on_before = bool(before.get("on"))
        flipped = await robot.robot_control.set_lights(on=not on_before)
        restored = await robot.robot_control.set_lights(on=on_before)
        steps.append(
            MutationStepResult(
                name="lights_toggle_restore",
                ok=bool(restored.get("on")) == on_before,
                detail=(
                    f"before={on_before} flipped={flipped.get('on')} "
                    f"restored={restored.get('on')}"
                ),
            )
        )
    except Exception as exc:
        steps.append(
            MutationStepResult(name="lights_toggle_restore", ok=False, detail=str(exc))
        )

    # clientData put / get / delete
    try:
        payload = {"source": "flex-testing-agent", "suite": "crs_off_tier_c"}
        put = await robot.client_data.put(CLIENT_DATA_KEY, payload)
        got = await robot.client_data.get(CLIENT_DATA_KEY)
        await robot.client_data.delete(CLIENT_DATA_KEY)
        steps.append(
            MutationStepResult(
                name="client_data_put_get_delete",
                ok=True,
                detail=f"put_keys={list(put.keys())} get_ok={bool(got)}",
            )
        )
    except Exception as exc:
        steps.append(
            MutationStepResult(
                name="client_data_put_get_delete",
                ok=False,
                detail=str(exc),
            )
        )
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
