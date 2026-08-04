"""Run CRS-off API tiers A/B/C with structured timing artifacts.

See ``docs/crs-testing.md``. Default order: Tier A (probe) → B → C.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.crs_off import (
    TierBResult,
    TierCResult,
    run_crs_off_tier_b,
    run_crs_off_tier_c,
)
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.capabilities.probe import ProbeResult, probe_robot
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.run_state import DesiredRunState
from flex_testing_agent.orchestration.timing import TimingSession
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

API_SUITE_DESCRIPTOR = CapabilityDescriptor(
    name="api_suite",
    description=(
        "CRS-off Tier A (probe) + B (parameterized GETs) + C (reversible "
        "mutations) with timing JSON. Requires ALLOW_MUTATIONS for B fixtures "
        "and C / camera."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    mutates_robot=True,
    requires_cleanup=True,
    max_execution_time_seconds=1800.0,
    evidence_produced=["api_suite.json", "timing"],
    preconditions=[
        "ALLOW_MUTATIONS=true",
        "CRS / accessControlEnabled is false",
    ],
)


class ApiSuiteResult(BaseModel):
    """Combined API suite outcome."""

    tier_a: ProbeResult | None = None
    tier_b: TierBResult | None = None
    tier_c: TierCResult | None = None
    timing_path: str | None = None
    ok: bool = False
    detail: str | None = None
    counts: dict[str, Any] = Field(default_factory=dict)


def _record_endpoint_spans(
    timing: TimingSession,
    *,
    tier: str,
    items: list[dict[str, Any]],
    limit: int = 25,
) -> None:
    """Record the slowest measured GETs as individual timing spans."""
    ranked = sorted(
        (item for item in items if item.get("duration_seconds") is not None),
        key=lambda item: float(item["duration_seconds"]),
        reverse=True,
    )[:limit]
    for item in ranked:
        name = str(item.get("name") or "unknown")
        timing.record(
            f"api.{tier}.get.{name}",
            float(item["duration_seconds"]),
            ok=bool(item.get("ok", True)),
            detail=str(item.get("path") or ""),
            meta={
                "status_code": item.get("status_code"),
                "tier": tier,
            },
        )


async def run_api_suite(
    robot: FlexRobot,
    *,
    take_picture: bool = True,
    create_fixtures: bool = True,
    protocol_path: Path | None = None,
) -> ApiSuiteResult:
    """Execute Tier A → B → C and write a timing report."""
    ensure_mutation_allowed(
        robot.settings,
        risk_level=API_SUITE_DESCRIPTOR.risk_level,
        capability_name=API_SUITE_DESCRIPTOR.name,
    )

    timing = TimingSession(
        label="api-suite",
        robot_host=robot.settings.robot_host,
        channel="external",
    )
    try:
        health = await robot.verify_health()
        timing.system_version = health.system_version
        timing.api_version = health.api_version
    except Exception as exc:
        timing.note(f"health: {exc}")

    result = ApiSuiteResult()
    soft_notes: list[str] = []

    log.info("api_suite_tier_a_start")
    async with timing.aspan("api.tier_a_probe"):
        tier_a = await probe_robot(
            robot,
            take_picture=take_picture,
            run_state=DesiredRunState.NO_CURRENT,
            ensure_run_state_flag=True,
        )
    result.tier_a = tier_a
    if tier_a.picture_error:
        soft_notes.append(f"tier_a_picture={tier_a.picture_error}")
        timing.note(f"picture: {tier_a.picture_error}")
    _record_endpoint_spans(
        timing,
        tier="a",
        items=list((tier_a.probe or {}).get("results") or []),
    )

    log.info("api_suite_tier_b_start")
    async with timing.aspan("api.tier_b_parameterized"):
        tier_b = await run_crs_off_tier_b(
            robot,
            create_fixtures=create_fixtures,
            protocol_path=protocol_path,
            run_state=DesiredRunState.CURRENT_IDLE,
            ensure_run_state_flag=True,
        )
    result.tier_b = tier_b
    _record_endpoint_spans(
        timing,
        tier="b",
        items=[r.model_dump(mode="json") for r in tier_b.results],
    )

    log.info("api_suite_tier_c_start")
    async with timing.aspan("api.tier_c_mutations"):
        tier_c = await run_crs_off_tier_c(
            robot,
            run_state=DesiredRunState.NO_CURRENT,
            ensure_run_state_flag=True,
        )
    result.tier_c = tier_c

    path = timing.write(robot.settings.ensure_artifact_directory() / "timing")
    result.timing_path = str(path)
    result.counts = {
        "tier_a_ok": tier_a.summary.probe_ok,
        "tier_a_failed": tier_a.summary.probe_failed,
        "tier_b_ok": tier_b.ok_count,
        "tier_b_failed": tier_b.fail_count,
        "tier_b_skipped": len(tier_b.skipped_paths),
        "tier_c_ok": tier_c.ok_count,
        "tier_c_failed": tier_c.fail_count,
    }
    hard_failures: list[str] = []
    if tier_a.summary.probe_failed:
        hard_failures.append(f"tier_a_failed={tier_a.summary.probe_failed}")
    if tier_b.fail_count:
        hard_failures.append(f"tier_b_failed={tier_b.fail_count}")
    if tier_c.fail_count:
        hard_failures.append(f"tier_c_failed={tier_c.fail_count}")
    result.ok = not hard_failures
    result.detail = "; ".join([*hard_failures, *soft_notes]) or None
    robot.raw_evidence["api_suite"] = result.model_dump(mode="json")
    return result
