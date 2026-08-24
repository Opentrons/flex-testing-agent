"""Unit tests for idleLogout activity refresh capability."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.idle_logout_activity import (
    DEFAULT_MARGIN_AFTER_IDLE_LOGOUT_S,
    IdleLogoutActivityPing,
    format_ping_table_rows,
    resolve_activity_duration,
    run_idle_logout_activity,
)
from flex_testing_agent.config.settings import Settings

_BASE = "http://127.0.0.1:31950"
_USER = {
    "username": "flex_test_operator",
    "fullName": "Flex Test Operator",
    "accountType": "user",
    "scopes": [],
    "locked": False,
    "resetPassword": False,
}
_SETTINGS_PAYLOAD = {
    "data": {
        "maxNumberOfLoginAttempts": 5,
        "passwordResetTime": None,
        "passwordComplexityMinimumLength": None,
        "passwordComplexitySpecialCharacters": None,
        "idleLogout": 180.0,
        "requireAdminCredsWhenUpdatingRobotSoftware": True,
        "requireAdminCredsWhenSendingProtocolToRobot": True,
        "requireAdminCredsForSignoffProtocol": False,
    }
}


@pytest.mark.unit
def test_resolve_activity_duration_defaults() -> None:
    assert resolve_activity_duration(idle_logout_seconds=180.0) == (
        180.0 + DEFAULT_MARGIN_AFTER_IDLE_LOGOUT_S
    )


@pytest.mark.unit
def test_resolve_activity_duration_override() -> None:
    assert (
        resolve_activity_duration(
            idle_logout_seconds=180.0,
            duration_seconds=95.0,
        )
        == 95.0
    )


@pytest.mark.unit
def test_format_ping_table_rows() -> None:
    rows = format_ping_table_rows(
        [
            IdleLogoutActivityPing(
                elapsed_seconds=30.0,
                introspect_active=True,
                self_get_ok=True,
            )
        ]
    )
    assert rows == [("30.0s", "yes", "yes", "")]


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_idle_logout_activity_passes_with_active_pings(tmp_path) -> None:
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
    respx.get(f"{_BASE}/auth/users/self").mock(
        return_value=httpx.Response(200, json={"data": _USER}),
    )

    clock = {"now": 0.0}

    def fake_monotonic() -> float:
        return clock["now"]

    async def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    with (
        patch(
            "flex_testing_agent.capabilities.idle_logout_activity."
            "access_token_for_username",
            new=AsyncMock(return_value="operator-tok"),
        ),
        patch(
            "flex_testing_agent.capabilities.idle_logout_activity.time.monotonic",
            side_effect=fake_monotonic,
        ),
        patch(
            "flex_testing_agent.capabilities.idle_logout_activity.asyncio.sleep",
            side_effect=fake_sleep,
        ),
    ):
        result = await run_idle_logout_activity(
            settings,
            username="flex_test_operator",
            activity_interval_seconds=30.0,
            margin_seconds=10.0,
        )

    assert result.ok is True
    assert result.duration_seconds == 190.0
    assert len(result.pings) >= 2


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_idle_logout_activity_fails_when_token_dies(tmp_path) -> None:
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
        return_value=httpx.Response(200, json={"active": False})
    )
    respx.get(f"{_BASE}/auth/users/self").mock(
        return_value=httpx.Response(401, json={"errors": [{"id": "Unauthorized"}]})
    )

    with (
        patch(
            "flex_testing_agent.capabilities.idle_logout_activity."
            "access_token_for_username",
            new=AsyncMock(return_value="operator-tok"),
        ),
        patch(
            "flex_testing_agent.capabilities.idle_logout_activity.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        result = await run_idle_logout_activity(
            settings,
            username="flex_test_operator",
            activity_interval_seconds=30.0,
            duration_seconds=60.0,
        )

    assert result.ok is False
    assert "invalidated" in result.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_idle_logout_activity_rejects_short_interval(tmp_path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        artifact_directory=tmp_path / "artifacts",
    )
    with pytest.raises(ValueError, match="activity_interval_seconds"):
        await run_idle_logout_activity(
            settings,
            activity_interval_seconds=1.0,
        )
