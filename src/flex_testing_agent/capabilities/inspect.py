"""Read-only inspect capability."""

from __future__ import annotations

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.models.snapshot import RobotSnapshot
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.robots.flex import FlexRobot

INSPECT_DESCRIPTOR = CapabilityDescriptor(
    name="inspect_robot",
    description=(
        "Connect to the configured Flex, query health and service versions, "
        "and detect access-control state without mutating the robot."
    ),
    risk_level=RiskLevel.READ_ONLY,
    mutates_robot=False,
    requires_cleanup=False,
    max_execution_time_seconds=60.0,
    required_robot_features=["health"],
    evidence_produced=[
        "health.json",
        "update_health.json",
        "access_control.json",
        "snapshot.json",
    ],
    preconditions=["ROBOT_HOST configured", "robot reachable over HTTP(S)"],
    input_schema={"type": "object", "properties": {}},
    output_schema={"type": "object", "properties": {"snapshot": {"type": "object"}}},
)


async def inspect_robot(robot: FlexRobot) -> RobotSnapshot:
    """Run the inspect capability against a Flex robot.

    Preconditions:
        - Robot host is configured on the robot's settings.
        - Capability is read-only (mutation gate is a no-op).

    Postconditions:
        - Returns a ``RobotSnapshot`` (connectivity may be false on total failure).
        - Populates ``robot.raw_evidence`` with successful raw payloads.
    """
    ensure_mutation_allowed(
        robot.settings,
        risk_level=INSPECT_DESCRIPTOR.risk_level,
        capability_name=INSPECT_DESCRIPTOR.name,
    )
    robot.settings.require_robot_host()
    return await robot.inspect()
