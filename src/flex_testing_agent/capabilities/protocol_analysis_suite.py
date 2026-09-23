"""Protocol analysis CRS behavior (RQA-6012).

Product intent: protocol analysis (upload-time and reanalysis) is simulation-only
and must not require login or documentation, even when CRS is on and
``requireReasonForInteraction`` is true.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.protocols import ProtocolsClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.protocol_analysis import (
    default_duolink_protocol_path,
    duolink_reanalysis_runtime_parameter_values,
    duolink_upload_runtime_parameter_values,
)
from flex_testing_agent.models.access_control import AccessControlState
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session

ANALYSIS_SUCCESS_STATUSES = frozenset({200, 201})

PROTOCOL_ANALYSIS_RQA6012_DESCRIPTOR = CapabilityDescriptor(
    name="protocol_analysis_rqa6012_retest",
    description=(
        "Verify POST /protocols/{id}/analyses with altered RTPs succeeds without "
        "auth or Opentrons-User-Notes when CRS is on (RQA-6012)."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    mutates_robot=True,
    requires_cleanup=True,
    max_execution_time_seconds=600.0,
    required_robot_features=["access_control"],
    evidence_produced=["rqa6012_retest"],
    preconditions=[
        "CRS enabled (access control on)",
        "ALLOW_MUTATIONS=true",
        "ROBOT_USE_HTTPS=true when CRS is on",
    ],
)


class Rqa6012ProbeStep(BaseModel):
    """One HTTP probe in the RQA-6012 retest."""

    step: str
    http_status: int | None = None
    detail: str = ""


class Rqa6012RetestResult(BaseModel):
    """Outcome for RQA-6012 analysis auth/documentation bypass retest."""

    ok: bool
    protocol_id: str | None = None
    require_reason_for_interaction: bool | None = None
    reanalysis_rtps: dict[str, Any] = Field(default_factory=dict)
    probes: list[Rqa6012ProbeStep] = Field(default_factory=list)
    detail: str = ""


def _analysis_ids(analyses: list[dict[str, Any]]) -> set[str]:
    return {str(item["id"]) for item in analyses if item.get("id") is not None}


async def _wait_initial_analysis(
    protocols: ProtocolsClient,
    protocol_id: str,
    *,
    timeout_seconds: float = 300.0,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        analyses = await protocols.list_analyses(protocol_id)
        if analyses:
            latest = analyses[0]
            status = str(latest.get("status") or "")
            analysis_id = latest.get("id")
            if status in {"completed", "succeeded"} and analysis_id is not None:
                return str(analysis_id)
            if status in {"not-ok", "failed", "error"}:
                msg = f"analysis failed: {latest!r}"
                raise RuntimeError(msg)
        await asyncio.sleep(1.0)
    msg = f"timed out waiting for initial analysis of {protocol_id}"
    raise TimeoutError(msg)


async def _wait_new_analysis(
    protocols: ProtocolsClient,
    protocol_id: str,
    *,
    known_ids: set[str],
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline:
        analyses = await protocols.list_analyses(protocol_id)
        for item in analyses:
            analysis_id = item.get("id")
            if analysis_id is None:
                continue
            aid = str(analysis_id)
            if aid in known_ids:
                continue
            last = item
            status = str(item.get("status") or "")
            if status in {"completed", "succeeded"}:
                return item
            if status in {"not-ok", "failed", "error"}:
                return item
        await asyncio.sleep(2.0)
    msg = f"timed out waiting for new analysis of {protocol_id}; last={last!r}"
    raise TimeoutError(msg)


async def _probe_create_analysis(
    protocols: ProtocolsClient,
    protocol_id: str,
    *,
    step: str,
    run_time_parameter_values: dict[str, Any] | None = None,
) -> Rqa6012ProbeStep:
    try:
        payload = await protocols.create_analysis(
            protocol_id,
            run_time_parameter_values=run_time_parameter_values,
        )
        detail = json.dumps(
            {
                "runTimeParameterValues": run_time_parameter_values,
                "response_excerpt": str(payload)[:300],
            }
        )
        return Rqa6012ProbeStep(step=step, http_status=200, detail=detail)
    except RobotApiError as exc:
        body = exc.body[:500] if exc.body else str(exc)
        return Rqa6012ProbeStep(
            step=step,
            http_status=exc.status_code,
            detail=body,
        )


async def run_rqa6012_retest(
    settings: Settings,
    *,
    admin_username: str = "flex_harness_admin",
    protocol_path: str | None = None,
    protocol_id: str | None = None,
    skip_cleanup: bool = False,
) -> Rqa6012RetestResult:
    """Retest RQA-6012: reanalysis with altered RTPs, no auth or documentation."""
    ensure_mutation_allowed(
        settings,
        risk_level=PROTOCOL_ANALYSIS_RQA6012_DESCRIPTOR.risk_level,
        capability_name=PROTOCOL_ANALYSIS_RQA6012_DESCRIPTOR.name,
    )
    probes: list[Rqa6012ProbeStep] = []
    if protocol_path is not None:
        duolink_path = Path(protocol_path)
    else:
        duolink_path = default_duolink_protocol_path()
    upload_rtps = duolink_upload_runtime_parameter_values()
    reanalysis_rtps = duolink_reanalysis_runtime_parameter_values()
    resolved_protocol_id = protocol_id
    require_reason: bool | None = None
    known_analysis_ids: set[str] = set()

    async with FlexRobot(settings) as preflight_robot:
        ac = await preflight_robot.auth_settings.detect_access_control()
        if ac.state != AccessControlState.ENABLED:
            result = Rqa6012RetestResult(
                ok=False,
                reanalysis_rtps=reanalysis_rtps,
                probes=probes,
                detail=(
                    "CRS must be enabled for RQA-6012 verification. "
                    "Run: ALLOW_MUTATIONS=true uv run flex-test crs enable "
                    "--confirm-one-way"
                ),
            )
            preflight_robot.raw_evidence["rqa6012_retest"] = result.model_dump(
                mode="json"
            )
            return result

    admin_token = await access_token_for_username(settings, admin_username)

    async with FlexRobot(settings, access_token=admin_token) as robot:
        audit_payload = await robot.audit.get_external_settings_raw()
        audit_data = audit_payload.get("data")
        if isinstance(audit_data, dict):
            raw = audit_data.get("requireReasonForInteraction")
            if isinstance(raw, bool):
                require_reason = raw
        probes.append(
            Rqa6012ProbeStep(
                step="audit_require_reason_for_interaction",
                detail=f"requireReasonForInteraction={require_reason}",
            )
        )

        if resolved_protocol_id is None:
            upload = await robot.protocols.upload_protocol(duolink_path, timeout=180.0)
            resolved_protocol_id = robot.protocols.protocol_id_from_upload(upload)
            if resolved_protocol_id is None:
                result = Rqa6012RetestResult(
                    ok=False,
                    require_reason_for_interaction=require_reason,
                    reanalysis_rtps=reanalysis_rtps,
                    probes=probes,
                    detail="protocol upload did not return an id",
                )
                robot.raw_evidence["rqa6012_retest"] = result.model_dump(mode="json")
                return result
            probes.append(
                Rqa6012ProbeStep(
                    step="upload_protocol",
                    http_status=201,
                    detail=f"{resolved_protocol_id} ({duolink_path.name})",
                )
            )
            await _wait_initial_analysis(robot.protocols, resolved_protocol_id)
        else:
            probes.append(
                Rqa6012ProbeStep(
                    step="use_existing_protocol",
                    detail=resolved_protocol_id,
                )
            )

        existing = await robot.protocols.list_analyses(resolved_protocol_id)
        known_analysis_ids = _analysis_ids(existing)
        probes.append(
            Rqa6012ProbeStep(
                step="baseline_analysis_count",
                detail=f"count={len(existing)} upload_rtps={upload_rtps}",
            )
        )

    failures: list[str] = []

    async with build_robot_http_session(settings) as anon_session:
        anon_protocols = ProtocolsClient(anon_session)
        probe = await _probe_create_analysis(
            anon_protocols,
            resolved_protocol_id,
            step="reanalysis_unauthenticated_altered_rtps",
            run_time_parameter_values=reanalysis_rtps,
        )
        probes.append(probe)
        if probe.http_status not in ANALYSIS_SUCCESS_STATUSES:
            failures.append(
                "unauthenticated POST /analyses with altered RTPs must return "
                f"200/201 (got {probe.http_status})"
            )
        else:
            analysis = await _wait_new_analysis(
                anon_protocols,
                resolved_protocol_id,
                known_ids=known_analysis_ids,
            )
            known_analysis_ids.add(str(analysis["id"]))
            probes.append(
                Rqa6012ProbeStep(
                    step="reanalysis_unauthenticated_completed",
                    detail=(
                        f"id={analysis.get('id')} status={analysis.get('status')} "
                        f"result={analysis.get('result')}"
                    ),
                )
            )
            if analysis.get("status") not in {"completed", "succeeded"}:
                failures.append(
                    "unauthenticated reanalysis did not complete successfully"
                )

    async with build_robot_http_session(
        settings,
        access_token=admin_token,
    ) as auth_session:
        auth_session.set_user_notes(None)
        auth_protocols = ProtocolsClient(auth_session)
        auth_rtps = dict(reanalysis_rtps)
        auth_rtps["num_sample"] = 24
        probe = await _probe_create_analysis(
            auth_protocols,
            resolved_protocol_id,
            step="reanalysis_authenticated_no_notes_altered_rtps",
            run_time_parameter_values=auth_rtps,
        )
        probes.append(probe)
        if probe.http_status == 451:
            failures.append(
                "authenticated POST /analyses without Opentrons-User-Notes "
                "must not return 451 when requireReasonForInteraction is on"
            )
        elif probe.http_status not in ANALYSIS_SUCCESS_STATUSES:
            failures.append(
                "authenticated POST /analyses without notes must return 200/201 "
                f"(got {probe.http_status})"
            )
        else:
            analysis = await _wait_new_analysis(
                auth_protocols,
                resolved_protocol_id,
                known_ids=known_analysis_ids,
            )
            probes.append(
                Rqa6012ProbeStep(
                    step="reanalysis_authenticated_no_notes_completed",
                    detail=(
                        f"id={analysis.get('id')} status={analysis.get('status')} "
                        f"result={analysis.get('result')}"
                    ),
                )
            )
            if analysis.get("status") not in {"completed", "succeeded"}:
                failures.append(
                    "authenticated reanalysis without notes did not complete"
                )

    if not skip_cleanup and resolved_protocol_id is not None and protocol_id is None:
        async with FlexRobot(settings, access_token=admin_token) as cleanup_robot:
            with contextlib.suppress(RobotApiError):
                await cleanup_robot.protocols.delete_protocol(resolved_protocol_id)
            probes.append(
                Rqa6012ProbeStep(
                    step="cleanup_delete_protocol",
                    detail=resolved_protocol_id,
                )
            )

    ok = not failures
    detail = (
        "reanalysis with altered RTPs bypasses auth and documentation (RQA-6012)"
        if ok
        else "; ".join(failures)
    )
    result = Rqa6012RetestResult(
        ok=ok,
        protocol_id=resolved_protocol_id,
        require_reason_for_interaction=require_reason,
        reanalysis_rtps=reanalysis_rtps,
        probes=probes,
        detail=detail,
    )

    async with FlexRobot(settings, access_token=admin_token) as evidence_robot:
        evidence_robot.raw_evidence["rqa6012_retest"] = result.model_dump(mode="json")

    return result
