"""Unit tests for idleLogout inactivity probe."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.idle_logout_inactivity import (
    DEFAULT_MARGIN_AFTER_IDLE_LOGOUT_S,
    resolve_inactivity_wait,
    run_idle_logout_inactivity,
)
from flex_testing_agent.config.settings import Settings

_BASE = "http://127.0.0.1:31950"
_SETTINGS_PAYLOAD = {
    "data": {
        "maxNumberOfLoginAttempts": 5,
        "passwordResetTime": None,
        "passwordComplexityMinimumLength": None,
        "passwordComplexitySpecialCharacters": None,
        "idleLogout": 60.0,
        "requireAdminCredsWhenUpdatingRobotSoftware": True,
        "requireAdminCredsWhenSendingProtocolToRobot": True,
        "requireAdminCredsForSignoffProtocol": False,
    }
}


@pytest.mark.unit
def test_resolve_inactivity_wait_defaults() -> None:
    assert resolve_inactivity_wait(idle_logout_seconds=60.0) == (
        60.0 + DEFAULT_MARGIN_AFTER_IDLE_LOGOUT_S
    )


@pytest.mark.unit
def test_resolve_inactivity_wait_override() -> None:
    assert (
        resolve_inactivity_wait(
            idle_logout_seconds=60.0,
            wait_seconds=70.0,
        )
        == 70.0
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_idle_logout_inactivity_passes_when_token_expires(tmp_path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        artifact_directory=tmp_path / "artifacts",
    )
    respx.get(f"{_BASE}/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"accessControlEnabled": True}},
        )
    )
    respx.get(f"{_BASE}/auth/settings").mock(
        return_value=httpx.Response(200, json=_SETTINGS_PAYLOAD)
    )
    introspect_calls = {"count": 0}

    def introspect_handler(_request: httpx.Request) -> httpx.Response:
        introspect_calls["count"] += 1
        active = introspect_calls["count"] == 1
        return httpx.Response(200, json={"active": active, "username": "op"})

    respx.post(f"{_BASE}/auth/oauth2/introspect").mock(side_effect=introspect_handler)

    with (
        patch(
            "flex_testing_agent.capabilities.idle_logout_inactivity."
            "access_token_for_username",
            new=AsyncMock(return_value="operator-tok"),
        ),
        patch(
            "flex_testing_agent.capabilities.idle_logout_inactivity.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        result = await run_idle_logout_inactivity(
            settings,
            username="flex_test_operator",
            wait_seconds=65.0,
        )

    assert result.ok is True
    assert result.introspect_active_before is True
    assert result.introspect_active_after is False
    assert "inactive after" in result.detail


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_idle_logout_inactivity_fails_when_token_stays_active(
    tmp_path,
) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        artifact_directory=tmp_path / "artifacts",
    )
    respx.get(f"{_BASE}/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"accessControlEnabled": True}},
        )
    )
    respx.get(f"{_BASE}/auth/settings").mock(
        return_value=httpx.Response(200, json=_SETTINGS_PAYLOAD)
    )
    respx.post(f"{_BASE}/auth/oauth2/introspect").mock(
        return_value=httpx.Response(200, json={"active": True, "username": "op"})
    )

    with (
        patch(
            "flex_testing_agent.capabilities.idle_logout_inactivity."
            "access_token_for_username",
            new=AsyncMock(return_value="operator-tok"),
        ),
        patch(
            "flex_testing_agent.capabilities.idle_logout_inactivity.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        result = await run_idle_logout_inactivity(
            settings,
            wait_seconds=65.0,
        )

    assert result.ok is False
    assert "still active" in result.detail
