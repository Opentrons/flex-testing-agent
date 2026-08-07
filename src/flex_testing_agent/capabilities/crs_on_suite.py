"""CRS-on API suite: authenticated Tier A + B + C with timing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.crs_off import TierBResult, TierCResult
from flex_testing_agent.capabilities.crs_on_matrix import run_auth_matrix
from flex_testing_agent.capabilities.crs_on_probe import CrsOnTierAResult, probe_crs_on
from flex_testing_agent.capabilities.crs_on_tier_b import run_crs_on_tier_b
from flex_testing_agent.capabilities.crs_on_tier_c import run_crs_on_tier_c
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.run_state import DesiredRunState
from flex_testing_agent.orchestration.timing import TimingSession
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

CRS_ON_SUITE = CapabilityDescriptor(
    name="crs_on_suite",
    description=(
        "CRS-on auth matrix + Tier A (GET probe + user-management API) + B + C "
        "with OAuth. Requires ALLOW_MUTATIONS."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    mutates_robot=True,
    requires_cleanup=True,
    max_execution_time_seconds=1800.0,
    evidence_produced=["crs_on_suite.json", "timing"],
    preconditions=[
        "ALLOW_MUTATIONS=true",
        "CRS / accessControlEnabled is true",
        "ROBOT_USE_HTTPS=true",
    ],
)


class CrsOnSuiteResult(BaseModel):
    """Combined CRS-on suite outcome."""

    tier_a: CrsOnTierAResult | None = None
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
    ranked = sorted(
        (item for item in items if item.get("duration_seconds") is not None),
        key=lambda item: float(item["duration_seconds"]),
        reverse=True,
    )[:limit]
    for item in ranked:
        name = str(item.get("name") or "unknown")
        timing.record(
            f"crs_on.{tier}.get.{name}",
            float(item["duration_seconds"]),
            ok=bool(item.get("ok", True)),
            detail=str(item.get("path") or ""),
            meta={
                "status_code": item.get("status_code"),
                "tier": tier,
            },
        )


async def run_crs_on_suite(
    settings: Settings,
    *,
    username: str = "flex_test_service",
    include_auth_matrix: bool = True,
    include_unauth_baseline: bool = False,
    create_fixtures: bool = True,
    protocol_path: Path | None = None,
) -> CrsOnSuiteResult:
    """Execute CRS-on matrix (optional) → Tier A → B → C with timing."""
    ensure_mutation_allowed(
        settings,
        risk_level=CRS_ON_SUITE.risk_level,
        capability_name=CRS_ON_SUITE.name,
    )

    timing = TimingSession(
        label="crs-on-suite",
        robot_host=settings.robot_host,
        channel="external",
    )
    try:
        async with FlexRobot(settings) as robot:
            health = await robot.verify_health()
        timing.system_version = health.system_version
        timing.api_version = health.api_version
    except Exception as exc:
        timing.note(f"health: {exc}")

    result = CrsOnSuiteResult()
    soft_notes: list[str] = []
    hard_failures: list[str] = []

    if include_auth_matrix:
        log.info("crs_on_suite_auth_matrix_start")
        async with timing.aspan("crs_on.auth_matrix"):
            matrix = await run_auth_matrix(settings)
        if matrix.fail_count:
            hard_failures.append(f"auth_matrix_failed={matrix.fail_count}")
        result.counts["auth_matrix_ok"] = matrix.ok_count
        result.counts["auth_matrix_failed"] = matrix.fail_count
        result.counts["auth_matrix_skipped"] = len(matrix.skipped)

    log.info("crs_on_suite_tier_a_start")
    async with timing.aspan("crs_on.tier_a"):
        tier_a, _baseline = await probe_crs_on(
            settings,
            username=username,
            ensure_run_state_flag=True,
            include_unauth_baseline=include_unauth_baseline,
            include_user_management=True,
        )
    result.tier_a = tier_a
    hard_failures.extend(tier_a.failure_summary())
    _record_endpoint_spans(
        timing,
        tier="a",
        items=list((tier_a.probe.probe or {}).get("results") or []),
    )
    if tier_a.user_management is not None:
        for step in tier_a.user_management.steps:
            timing.record(
                f"crs_on.tier_a.users.{step.name}",
                0.0,
                ok=step.ok,
                detail=step.path,
                meta={"method": step.method},
            )

    log.info("crs_on_suite_tier_b_start")
    async with timing.aspan("crs_on.tier_b_parameterized"):
        tier_b = await run_crs_on_tier_b(
            settings,
            username=username,
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
    if tier_b.fail_count:
        hard_failures.append(f"tier_b_failed={tier_b.fail_count}")

    log.info("crs_on_suite_tier_c_start")
    async with timing.aspan("crs_on.tier_c_mutations"):
        tier_c = await run_crs_on_tier_c(
            settings,
            username=username,
            run_state=DesiredRunState.NO_CURRENT,
            ensure_run_state_flag=True,
        )
    result.tier_c = tier_c
    if tier_c.fail_count:
        hard_failures.append(f"tier_c_failed={tier_c.fail_count}")

    path = timing.write(settings.ensure_artifact_directory() / "timing")
    result.timing_path = str(path)
    result.counts.update(
        {
            "tier_a_probe_ok": tier_a.probe_ok,
            "tier_a_probe_failed": tier_a.probe_failed,
            "tier_a_users_ok": tier_a.users_ok,
            "tier_a_users_failed": tier_a.users_failed,
            "tier_a_ok": tier_a.probe_ok + tier_a.users_ok,
            "tier_a_failed": tier_a.probe_failed + tier_a.users_failed,
            "tier_b_ok": tier_b.ok_count,
            "tier_b_failed": tier_b.fail_count,
            "tier_b_skipped": len(tier_b.skipped_paths),
            "tier_c_ok": tier_c.ok_count,
            "tier_c_failed": tier_c.fail_count,
        }
    )
    result.ok = not hard_failures
    result.detail = "; ".join([*hard_failures, *soft_notes]) or None

    out = settings.ensure_artifact_directory() / "crs_on_suite.json"
    out.write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return result
