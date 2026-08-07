"""CRS-on Tier B: parameterized GET probes with OAuth bearer token."""

from __future__ import annotations

from pathlib import Path

from flex_testing_agent.capabilities.crs_auth import (
    access_token_for_username,
    ensure_crs_on,
)
from flex_testing_agent.capabilities.crs_off import TierBResult, _execute_tier_b
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.run_state import DesiredRunState
from flex_testing_agent.robots.flex import FlexRobot

CRS_ON_TIER_B = CapabilityDescriptor(
    name="crs_on_tier_b",
    description=(
        "CRS-on Tier B: parameterized catalog GETs with OAuth bearer token. "
        "Default run presence: current-idle. Optionally create fixtures when "
        "ALLOW_MUTATIONS=true."
    ),
    risk_level=RiskLevel.READ_ONLY,
    evidence_produced=["crs_on_tier_b.json"],
    preconditions=[
        "CRS / accessControlEnabled is true",
        "ROBOT_USE_HTTPS=true and CA trust configured",
        "OAuth token for --as-user",
    ],
)


async def run_crs_on_tier_b(
    settings: Settings,
    *,
    username: str = "flex_test_operator",
    create_fixtures: bool = False,
    protocol_path: Path | None = None,
    run_state: DesiredRunState = DesiredRunState.CURRENT_IDLE,
    ensure_run_state_flag: bool = False,
) -> TierBResult:
    """Probe parameterized catalog GETs with an authenticated session."""
    token = await access_token_for_username(settings, username)
    async with FlexRobot(settings, access_token=token) as robot:
        await ensure_crs_on(robot)
        return await _execute_tier_b(
            robot,
            create_fixtures=create_fixtures,
            protocol_path=protocol_path,
            run_state=run_state,
            ensure_run_state_flag=ensure_run_state_flag,
            evidence_key="crs_on_tier_b",
            capability_prefix="crs_on_tier_b",
            auth_username=username,
        )
