"""Install capability safety gate tests."""

from __future__ import annotations

import pytest

from flex_testing_agent.capabilities.install import INSTALL_DESCRIPTOR, install_build
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.orchestration.gates import MutationDeniedError
from flex_testing_agent.robots.flex import FlexRobot


@pytest.mark.unit
@pytest.mark.asyncio
async def test_install_blocked_when_mutations_disabled(
    settings: Settings,
) -> None:
    settings.allow_mutations = False
    robot = FlexRobot(settings)
    with pytest.raises(MutationDeniedError, match="ALLOW_MUTATIONS"):
        await install_build(robot, "9.1.2-alpha.0")
    await robot.aclose()


@pytest.mark.unit
def test_install_descriptor_is_installation_risk() -> None:
    assert INSTALL_DESCRIPTOR.mutates_robot is True
    assert INSTALL_DESCRIPTOR.risk_level.value == "INSTALLATION"
