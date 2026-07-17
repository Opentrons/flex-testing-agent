"""Unit tests for mutation and dry-run gates."""

from __future__ import annotations

import pytest

from flex_testing_agent.capabilities.blocked import enable_access_control
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import (
    MutationDeniedError,
    ensure_mutation_allowed,
)


@pytest.mark.unit
def test_read_only_allowed_when_mutations_disabled() -> None:
    settings = Settings(allow_mutations=False)
    ensure_mutation_allowed(
        settings,
        risk_level=RiskLevel.READ_ONLY,
        capability_name="inspect_robot",
    )


@pytest.mark.unit
def test_mutating_blocked_by_default() -> None:
    settings = Settings(allow_mutations=False, dry_run=False)
    with pytest.raises(MutationDeniedError, match="ALLOW_MUTATIONS"):
        ensure_mutation_allowed(
            settings,
            risk_level=RiskLevel.REVERSIBLE_MUTATION,
            capability_name="example",
        )


@pytest.mark.unit
def test_mutating_blocked_by_dry_run() -> None:
    settings = Settings(allow_mutations=True, dry_run=True)
    with pytest.raises(MutationDeniedError, match="DRY_RUN"):
        ensure_mutation_allowed(
            settings,
            risk_level=RiskLevel.DISRUPTIVE,
            capability_name="example",
        )


@pytest.mark.unit
def test_physical_motion_always_blocked() -> None:
    settings = Settings(allow_mutations=True, dry_run=False)
    with pytest.raises(MutationDeniedError, match="physical motion"):
        ensure_mutation_allowed(
            settings,
            risk_level=RiskLevel.PHYSICAL_MOTION,
            capability_name="move_gantry",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enable_access_control_blocked_even_if_mutations_allowed() -> None:
    settings = Settings(allow_mutations=True, dry_run=False)
    with pytest.raises(MutationDeniedError, match="not implemented"):
        await enable_access_control(settings)
