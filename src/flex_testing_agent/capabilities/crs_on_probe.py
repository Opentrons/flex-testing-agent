"""CRS-on read-only probe (authenticated Tier A GETs + user-management API)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from pydantic import BaseModel

from flex_testing_agent.capabilities.crs_auth import (
    access_token_for_username,
    ensure_crs_on,
)
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.capabilities.probe import ProbeResult, probe_robot
from flex_testing_agent.capabilities.user_management_suite import (
    UserManagementSuiteResult,
    run_user_management_suite,
)
from flex_testing_agent.clients.readonly import ReadonlyClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.run_state import DesiredRunState
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session

CRS_ON_PROBE = CapabilityDescriptor(
    name="crs_on_probe",
    description=(
        "CRS-on Tier A: catalogued parameter-free GETs with OAuth, plus "
        "auth-server user-management REST verb coverage (idempotent CRUD)."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    mutates_robot=True,
    requires_cleanup=True,
    evidence_produced=[
        "crs_on_probe.json",
        "crs_on_user_management.json",
        "robot_state_summary.json",
    ],
    preconditions=[
        "CRS / accessControlEnabled is true",
        "ROBOT_USE_HTTPS=true and CA trust configured",
        "ALLOW_MUTATIONS=true (user-management API suite)",
    ],
)


@dataclass(frozen=True, slots=True)
class CrsOnBaselineResult:
    unauthenticated_denied: int
    unauthenticated_ok: int
    sample_denied_paths: list[str]


class CrsOnTierAResult(BaseModel):
    """Tier A: authenticated GET probe plus user-management API suite."""

    probe: ProbeResult
    user_management: UserManagementSuiteResult | None = None

    @property
    def probe_ok(self) -> int:
        return self.probe.summary.probe_ok

    @property
    def probe_failed(self) -> int:
        return self.probe.summary.probe_failed

    @property
    def users_ok(self) -> int:
        if self.user_management is None:
            return 0
        return self.user_management.ok_count

    @property
    def users_failed(self) -> int:
        if self.user_management is None:
            return 0
        return self.user_management.fail_count

    @property
    def ok(self) -> bool:
        return self.probe_failed == 0 and self.users_failed == 0

    def failure_summary(self) -> list[str]:
        parts: list[str] = []
        if self.probe_failed:
            parts.append(f"get_probe_failed={self.probe_failed}")
        if self.users_failed:
            parts.append(f"users_api_failed={self.users_failed}")
        return parts


async def probe_unauthenticated_baseline(
    settings: Settings,
) -> CrsOnBaselineResult:
    """Sample CRS-on GET catalog without a bearer token (expect success)."""
    denied = 0
    ok = 0
    samples: list[str] = []
    async with build_robot_http_session(settings) as session:
        readonly = ReadonlyClient(session)
        report = await readonly.probe_all()
    for result in report.results:
        if result.ok:
            ok += 1
        elif result.status_code in (401, 403):
            denied += 1
            if len(samples) < 5 and result.path not in samples:
                samples.append(result.path)
    return CrsOnBaselineResult(
        unauthenticated_denied=denied,
        unauthenticated_ok=ok,
        sample_denied_paths=samples,
    )


async def probe_crs_on(
    settings: Settings,
    *,
    username: str,
    admin_username: str = "flex_harness_admin",
    ensure_run_state_flag: bool = False,
    include_unauth_baseline: bool = True,
    include_user_management: bool = True,
) -> tuple[CrsOnTierAResult, CrsOnBaselineResult | None]:
    """Run CRS-on Tier A: authenticated GET probe + user-management API suite."""
    baseline: CrsOnBaselineResult | None = None
    if include_unauth_baseline:
        baseline = await probe_unauthenticated_baseline(settings)

    token = await access_token_for_username(settings, username)
    async with FlexRobot(settings, access_token=token) as robot:
        await ensure_crs_on(robot)
        probe = await probe_robot(
            robot,
            take_picture=False,
            run_state=DesiredRunState.NO_CURRENT,
            ensure_run_state_flag=ensure_run_state_flag,
        )
        robot.raw_evidence["crs_on_probe"] = {
            "username": username,
            "probe_ok": probe.summary.probe_ok,
            "probe_failed": probe.summary.probe_failed,
            "baseline": None if baseline is None else asdict(baseline),
        }

    user_management: UserManagementSuiteResult | None = None
    if include_user_management:
        ensure_mutation_allowed(
            settings,
            risk_level=CRS_ON_PROBE.risk_level,
            capability_name=f"{CRS_ON_PROBE.name}_users",
        )
        user_management = await run_user_management_suite(
            settings,
            admin_username=admin_username,
        )

    tier_a = CrsOnTierAResult(probe=probe, user_management=user_management)
    return tier_a, baseline
