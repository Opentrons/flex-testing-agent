"""Unit tests for CRS fixture user preflight."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flex_testing_agent.capabilities.fixture_preflight import (
    AuthSettingsSnapshot,
    FixtureUserInspection,
    inspect_fixture_user,
    probe_fixture_ropc,
    run_fixture_preflight,
)
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.auth_users import UserResponse


def _settings() -> Settings:
    return Settings(robot_host="192.168.0.21", allow_mutations=True)


def _user(
    *,
    username: str = "flex_test_operator",
    locked: bool = False,
    reset_password: bool = False,
) -> UserResponse:
    return UserResponse(
        username=username,
        fullName="Operator",
        accountType="user",
        scopes=[],
        locked=locked,
        resetPassword=reset_password,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_fixture_ropc_ok() -> None:
    settings = _settings()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_oauth = AsyncMock()
    mock_oauth.get_token = AsyncMock(return_value=MagicMock())

    with (
        patch(
            "flex_testing_agent.capabilities.fixture_preflight.build_robot_http_session",
            return_value=mock_session,
        ),
        patch(
            "flex_testing_agent.capabilities.fixture_preflight.OAuthClient",
            return_value=mock_oauth,
        ),
    ):
        result = await probe_fixture_ropc(settings, "flex_test_operator", "pw")

    assert result == "ok"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_fixture_ropc_invalid_grant() -> None:
    settings = _settings()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_oauth = AsyncMock()
    mock_oauth.get_token = AsyncMock(
        side_effect=RobotApiError(
            "bad",
            status_code=400,
            body='{"error":"invalid_grant"}',
        ),
    )

    with (
        patch(
            "flex_testing_agent.capabilities.fixture_preflight.build_robot_http_session",
            return_value=mock_session,
        ),
        patch(
            "flex_testing_agent.capabilities.fixture_preflight.OAuthClient",
            return_value=mock_oauth,
        ),
    ):
        result = await probe_fixture_ropc(settings, "flex_test_operator", "pw")

    assert result == "invalid_grant"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_inspect_fixture_user_primary_works() -> None:
    settings = _settings()
    admin = AsyncMock()
    admin.users.get_user_by_username = AsyncMock(return_value=_user())

    with (
        patch(
            "flex_testing_agent.capabilities.fixture_preflight.resolve_user_password_pair",
            return_value=("primary", "alternate"),
        ),
        patch(
            "flex_testing_agent.capabilities.fixture_preflight.probe_fixture_ropc",
            new_callable=AsyncMock,
            return_value="ok",
        ),
    ):
        inspection = await inspect_fixture_user(
            settings,
            admin,
            username="flex_test_operator",
            admin_token="admin-tok",
        )

    assert inspection.login_ok
    assert inspection.working_credential == "primary"
    assert inspection.needs_repair is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_fixture_preflight_reports_missing_user() -> None:
    settings = _settings()
    missing = FixtureUserInspection(
        username="flex_test_operator",
        exists=False,
        locked=None,
        reset_password=None,
        primary_probe="skipped",
        alternate_probe="skipped",
        working_credential=None,
        repair_actions=(),
    )
    mock_robot = AsyncMock()
    mock_robot.auth_settings.get_settings = AsyncMock(return_value=MagicMock())
    mock_robot.__aenter__ = AsyncMock(return_value=mock_robot)
    mock_robot.__aexit__ = AsyncMock(return_value=False)
    auth_snapshot = AuthSettingsSnapshot(
        require_admin_creds_when_sending_protocol_to_robot=True,
        require_admin_creds_when_updating_robot_software=True,
        require_admin_creds_for_signoff_protocol=False,
        idle_logout=59940.0,
    )

    with (
        patch(
            "flex_testing_agent.capabilities.fixture_preflight._admin_token_for_preflight",
            new_callable=AsyncMock,
            return_value="admin-tok",
        ),
        patch(
            "flex_testing_agent.capabilities.fixture_preflight.inspect_fixture_user",
            new_callable=AsyncMock,
            return_value=missing,
        ),
        patch(
            "flex_testing_agent.capabilities.fixture_preflight.FlexRobot",
            return_value=mock_robot,
        ),
        patch(
            "flex_testing_agent.capabilities.fixture_preflight.AuthSettingsSnapshot.from_settings",
            return_value=auth_snapshot,
        ),
    ):
        result = await run_fixture_preflight(
            settings,
            usernames=("flex_test_operator",),
            repair=False,
        )

    assert result.ok is False
    assert "flex_test_operator" in result.detail
