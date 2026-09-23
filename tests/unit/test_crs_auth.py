"""Unit tests for CRS OAuth login and resetPassword clearing via API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from flex_testing_agent.capabilities.crs_auth import (
    access_token_for_username,
    clear_pending_password_reset_via_api,
    recover_fixture_login_via_admin_reset,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.auth_users import ResetPasswordResponse, UserResponse


def _settings() -> Settings:
    return Settings(robot_host="192.168.0.21", allow_mutations=True)


def _user(
    *,
    username: str = "flex_harness_admin",
    reset_password: bool = False,
) -> UserResponse:
    return UserResponse(
        username=username,
        fullName="Test User",
        accountType="admin",
        scopes=[],
        locked=False,
        resetPassword=reset_password,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_access_token_for_username_returns_token_when_no_reset_pending() -> None:
    settings = _settings()

    with (
        patch(
            "flex_testing_agent.capabilities.crs_auth._ropc_access_token",
            new_callable=AsyncMock,
            return_value="tok-active",
        ) as ropc,
        patch(
            "flex_testing_agent.capabilities.crs_auth._finalize_robot_login",
            new_callable=AsyncMock,
            return_value="tok-active",
        ) as finalize,
    ):
        token = await access_token_for_username(settings, "flex_harness_admin")

    assert token == "tok-active"
    ropc.assert_awaited_once()
    finalize.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_pending_password_reset_via_api_self_patch_and_remint() -> None:
    settings = _settings()
    updated = _user(reset_password=False)
    mock_robot = AsyncMock()
    mock_robot.users.update_self = AsyncMock(return_value=updated)
    mock_robot.__aenter__ = AsyncMock(return_value=mock_robot)
    mock_robot.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "flex_testing_agent.capabilities.crs_auth.FlexRobot",
            return_value=mock_robot,
        ),
        patch(
            "flex_testing_agent.capabilities.crs_auth._ropc_access_token",
            new_callable=AsyncMock,
            return_value="tok-cleared",
        ) as ropc,
    ):
        token = await clear_pending_password_reset_via_api(
            settings,
            username="flex_harness_admin",
            access_token="tok-pending",
            new_password="FlexHarnessAdmin2!",
        )

    assert token == "tok-cleared"
    mock_robot.users.update_self.assert_awaited_once()
    ropc.assert_awaited_once_with(settings, "flex_harness_admin", "FlexHarnessAdmin2!")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_pending_password_reset_raises_when_flag_remains() -> None:
    settings = _settings()
    updated = _user(reset_password=True)
    mock_robot = AsyncMock()
    mock_robot.users.update_self = AsyncMock(return_value=updated)
    mock_robot.__aenter__ = AsyncMock(return_value=mock_robot)
    mock_robot.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "flex_testing_agent.capabilities.crs_auth.FlexRobot",
            return_value=mock_robot,
        ),
        pytest.raises(RuntimeError, match="resetPassword=true"),
    ):
        await clear_pending_password_reset_via_api(
            settings,
            username="flex_harness_admin",
            access_token="tok-pending",
            new_password="FlexHarnessAdmin2!",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finalize_login_skips_reset_when_repair_disabled() -> None:
    settings = _settings()
    mock_robot = AsyncMock()
    mock_robot.users.get_self = AsyncMock(return_value=_user(reset_password=True))
    mock_robot.__aenter__ = AsyncMock(return_value=mock_robot)
    mock_robot.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "flex_testing_agent.capabilities.crs_auth.FlexRobot",
            return_value=mock_robot,
        ),
        patch(
            "flex_testing_agent.capabilities.crs_auth._ropc_access_token",
            new_callable=AsyncMock,
            return_value="tok-pending",
        ),
        pytest.raises(RuntimeError, match="resetPassword=true"),
    ):
        await access_token_for_username(
            settings,
            "flex_harness_admin",
            allow_admin_recovery=False,
            repair_reset_password=False,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_first_available_admin_token_does_not_recursively_recover() -> None:
    settings = _settings()
    calls: list[str] = []

    async def fake_access(
        _settings: Settings,
        username: str,
        *,
        allow_admin_recovery: bool = True,
        repair_reset_password: bool = True,
    ) -> str:
        del repair_reset_password
        calls.append(f"{username}:{allow_admin_recovery}")
        msg = f"login failed for {username}"
        raise RuntimeError(msg)

    with patch(
        "flex_testing_agent.capabilities.crs_auth.access_token_for_username",
        side_effect=fake_access,
    ):
        from flex_testing_agent.capabilities.crs_auth import (
            _first_available_admin_token,
        )

        token = await _first_available_admin_token(
            settings,
            exclude_username="flex_test_operator",
        )

    assert token is None
    assert calls == [
        "flex_backup_admin:False",
        "flex_test_admin:False",
        "flex_harness_admin:False",
    ]

    settings = _settings()
    reset = ResetPasswordResponse(
        username="flex_test_admin",
        fullName="Flex test administrator",
        accountType="admin",
        scopes=[],
        locked=False,
        resetPassword=True,
        temporaryPassword="temp1234",
    )
    mock_robot = AsyncMock()
    mock_robot.users.reset_password = AsyncMock(return_value=reset)
    mock_robot.__aenter__ = AsyncMock(return_value=mock_robot)
    mock_robot.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "flex_testing_agent.capabilities.crs_auth.FlexRobot",
            return_value=mock_robot,
        ),
        patch(
            "flex_testing_agent.capabilities.crs_auth._ropc_access_token",
            new_callable=AsyncMock,
            return_value="tok-temp",
        ),
        patch(
            "flex_testing_agent.capabilities.crs_auth.clear_pending_password_reset_via_api",
            new_callable=AsyncMock,
            return_value="tok-lab",
        ) as clear_reset,
    ):
        token = await recover_fixture_login_via_admin_reset(
            settings,
            target_username="flex_test_admin",
            admin_token="admin-tok",
            lab_password="FlexHarnessUsers1!",
        )

    assert token == "tok-lab"
    mock_robot.users.reset_password.assert_awaited_once_with(
        "flex_test_admin",
        access_token="admin-tok",
    )
    clear_reset.assert_awaited_once_with(
        settings,
        username="flex_test_admin",
        access_token="tok-temp",
        new_password="FlexHarnessUsers1!",
    )
