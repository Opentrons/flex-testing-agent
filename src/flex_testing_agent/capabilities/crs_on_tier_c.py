"""CRS-on Tier C: reversible mutations with OAuth bearer token."""

from __future__ import annotations

from flex_testing_agent.capabilities.crs_auth import (
    access_token_for_username,
    ensure_crs_on,
)
from flex_testing_agent.capabilities.crs_off import TierCResult, _execute_tier_c
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.run_state import DesiredRunState
from flex_testing_agent.robots.flex import FlexRobot

CRS_ON_TIER_C = CapabilityDescriptor(
    name="crs_on_tier_c",
    description=(
        "CRS-on Tier C: reversible mutations with OAuth (lights, clientData, "
        "camera, errorRecovery, labwareOffsets, throwaway protocol/run delete). "
        "Requires ALLOW_MUTATIONS=true. Default run presence: no-current."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    mutates_robot=True,
    requires_cleanup=True,
    evidence_produced=["crs_on_tier_c.json"],
    preconditions=[
        "ALLOW_MUTATIONS=true",
        "CRS / accessControlEnabled is true",
        "ROBOT_USE_HTTPS=true and CA trust configured",
        "OAuth token for --as-user (default flex_test_service for run mutations)",
    ],
)


async def run_crs_on_tier_c(
    settings: Settings,
    *,
    username: str = "flex_test_service",
    run_state: DesiredRunState = DesiredRunState.NO_CURRENT,
    ensure_run_state_flag: bool = True,
) -> TierCResult:
    """Run reversible CRS-on mutations with an authenticated session."""
    ensure_mutation_allowed(
        settings,
        risk_level=CRS_ON_TIER_C.risk_level,
        capability_name=CRS_ON_TIER_C.name,
    )
    token = await access_token_for_username(settings, username)
    async with FlexRobot(settings, access_token=token) as robot:
        await ensure_crs_on(robot)
        return await _execute_tier_c(
            robot,
            run_state=run_state,
            ensure_run_state_flag=ensure_run_state_flag,
            evidence_key="crs_on_tier_c",
            run_state_capability="crs_on_tier_c_run_state",
            suite_label="crs_on_tier_c",
            run_signoff_label=f"{username} flex-testing-agent",
        )
