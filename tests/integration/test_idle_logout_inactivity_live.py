"""Live idleLogout inactivity probe against KansasFLEX (opt-in)."""

from __future__ import annotations

import os

import pytest

from flex_testing_agent.capabilities.idle_logout_inactivity import (
    run_idle_logout_inactivity,
)
from flex_testing_agent.config.settings import Settings, clear_settings_cache

_MAX_LIVE_IDLE_LOGOUT_S = 120.0


@pytest.mark.requires_robot
@pytest.mark.asyncio
async def test_live_idle_logout_inactivity_expires_token() -> None:
    """Token becomes inactive after idle wait with no API traffic."""
    if not os.environ.get("ROBOT_HOST"):
        pytest.skip("ROBOT_HOST not configured")
    if os.environ.get("ROBOT_USE_HTTPS", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("ROBOT_USE_HTTPS required for CRS-on idle logout test")

    clear_settings_cache()
    settings = Settings()
    wait_override = os.environ.get("IDLE_LOGOUT_WAIT_SECONDS")
    if wait_override is not None:
        wait_seconds = float(wait_override)
    else:
        from flex_testing_agent.capabilities.crs_auth import access_token_for_username
        from flex_testing_agent.robots.flex import FlexRobot

        token = await access_token_for_username(settings, "flex_test_operator")
        async with FlexRobot(settings, access_token=token) as robot:
            idle_logout = (await robot.auth_settings.get_settings()).idle_logout
        if idle_logout > _MAX_LIVE_IDLE_LOGOUT_S:
            pytest.skip(
                f"idleLogout={idle_logout}s is too long for default live probe; "
                "run settings-suite S6 first or set IDLE_LOGOUT_WAIT_SECONDS"
            )
        wait_seconds = idle_logout + 5.0

    result = await run_idle_logout_inactivity(
        settings,
        username=os.environ.get("IDLE_LOGOUT_TEST_USER", "flex_test_operator"),
        wait_seconds=wait_seconds,
    )
    assert result.ok, result.detail
