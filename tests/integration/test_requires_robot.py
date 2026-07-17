"""Opt-in read-only tests against a physical Flex robot."""

from __future__ import annotations

import os

import pytest

from flex_testing_agent.config.settings import Settings, clear_settings_cache
from flex_testing_agent.robots.flex import FlexRobot


@pytest.mark.requires_robot
@pytest.mark.asyncio
async def test_live_robot_inspect_read_only() -> None:
    """Connect to ROBOT_HOST and inspect without mutating.

    Skipped unless ROBOT_HOST is set in the environment.
    """
    if not os.environ.get("ROBOT_HOST"):
        pytest.skip("ROBOT_HOST not configured")

    clear_settings_cache()
    settings = Settings()
    async with FlexRobot(settings) as robot:
        snapshot = await robot.inspect()

    assert snapshot.host == settings.require_robot_host()
    # Soft assertion: connectivity preferred, but collect errors for diagnosis.
    if not snapshot.connectivity:
        pytest.fail(f"Robot unreachable: {snapshot.errors}")
