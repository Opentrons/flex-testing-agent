"""Live idleLogout activity test against KansasFLEX (opt-in)."""

from __future__ import annotations

import os

import pytest

from flex_testing_agent.capabilities.idle_logout_activity import (
    run_idle_logout_activity,
)
from flex_testing_agent.config.settings import Settings, clear_settings_cache


@pytest.mark.requires_robot
@pytest.mark.asyncio
async def test_live_idle_logout_activity_keeps_token_alive() -> None:
    """Same token stays valid when authenticated API calls continue past idleLogout."""
    if not os.environ.get("ROBOT_HOST"):
        pytest.skip("ROBOT_HOST not configured")
    if os.environ.get("ROBOT_USE_HTTPS", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("ROBOT_USE_HTTPS required for CRS-on idle logout test")

    clear_settings_cache()
    settings = Settings()
    result = await run_idle_logout_activity(
        settings,
        username=os.environ.get("IDLE_LOGOUT_TEST_USER", "flex_test_operator"),
        activity_interval_seconds=float(
            os.environ.get("IDLE_LOGOUT_ACTIVITY_INTERVAL", "30")
        ),
        margin_seconds=float(os.environ.get("IDLE_LOGOUT_MARGIN_SECONDS", "30")),
        duration_seconds=(
            float(os.environ["IDLE_LOGOUT_DURATION_SECONDS"])
            if os.environ.get("IDLE_LOGOUT_DURATION_SECONDS")
            else None
        ),
    )
    assert result.ok, result.detail
