"""Small reusable robot-under-test protocol."""

from __future__ import annotations

from typing import Protocol

from flex_testing_agent.models.health import HealthReport
from flex_testing_agent.models.snapshot import RobotSnapshot


class RobotUnderTest(Protocol):
    """Minimal interface for harness robot backends.

    Keep this surface small. Optional capabilities (install, mode transition,
    restore) can be added as separate protocols later.
    """

    async def inspect(self) -> RobotSnapshot:
        """Capture identity, versions, health, and detected mode."""
        ...

    async def verify_health(self) -> HealthReport:
        """Fetch robot-server health and raise on hard failure."""
        ...
