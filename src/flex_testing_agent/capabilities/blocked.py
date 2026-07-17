"""Explicitly blocked capabilities for documentation and gate tests."""

from __future__ import annotations

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import (
    MutationDeniedError,
    ensure_mutation_allowed,
)

ENABLE_ACCESS_CONTROL_DESCRIPTOR = CapabilityDescriptor(
    name="enable_access_control",
    description=(
        "BLOCKED: Enabling access control is one-way via the robot API "
        "(PATCH accepts only true). Not implemented in this harness."
    ),
    risk_level=RiskLevel.DISRUPTIVE,
    mutates_robot=True,
    requires_cleanup=True,
    max_execution_time_seconds=30.0,
    required_robot_features=["access_control"],
    evidence_produced=[],
    preconditions=["Never enable on Kansas without a documented restore path"],
)


async def enable_access_control(settings: Settings) -> None:
    """Refuse to enable access control.

    Raises:
        MutationDeniedError: Always, either via the mutation gate or explicit block.
    """
    ensure_mutation_allowed(
        settings,
        risk_level=ENABLE_ACCESS_CONTROL_DESCRIPTOR.risk_level,
        capability_name=ENABLE_ACCESS_CONTROL_DESCRIPTOR.name,
    )
    raise MutationDeniedError(
        "enable_access_control is not implemented: the robot API cannot "
        "disable access control once enabled without Opentrons assistance."
    )
