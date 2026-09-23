"""Unit tests for CRS enable capability."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.crs_on import (
    HARNESS_IDLE_LOGOUT_SECONDS,
    run_enable_crs,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.robots.flex import FlexRobot


def _user_json(username: str, *, account_type: str = "admin") -> dict[str, object]:
    return {
        "data": {
            "username": username,
            "fullName": username,
            "accountType": account_type,
            "scopes": [],
            "locked": False,
            "resetPassword": False,
        }
    }


def _auth_settings_json(*, idle_logout: float = 180.0) -> dict[str, object]:
    return {
        "data": {
            "maxNumberOfLoginAttempts": 5,
            "passwordResetTime": None,
            "passwordComplexityMinimumLength": None,
            "passwordComplexitySpecialCharacters": None,
            "idleLogout": idle_logout,
            "requireAdminCredsWhenUpdatingRobotSoftware": True,
            "requireAdminCredsWhenSendingProtocolToRobot": True,
            "requireAdminCredsForSignoffProtocol": False,
        }
    }


def _settings() -> Settings:
    return Settings(
        robot_host="192.168.0.21",
        allow_mutations=True,
        # Isolate from lab .env CRS_ADMIN_* overrides.
        crs_admin_username=None,
        crs_admin_password=None,
    )


def _mock_oauth_and_idle_logout(base: str) -> None:
    respx.post(f"{base}/auth/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "bootstrap-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )
    respx.get(f"{base}/auth/settings").mock(
        return_value=httpx.Response(200, json=_auth_settings_json(idle_logout=180.0))
    )
    respx.patch(f"{base}/auth/settings").mock(
        return_value=httpx.Response(
            200,
            json=_auth_settings_json(idle_logout=HARNESS_IDLE_LOGOUT_SECONDS),
        )
    )


@pytest.mark.asyncio
async def test_run_enable_crs_requires_confirm() -> None:
    settings = _settings()
    async with FlexRobot(settings) as robot:
        with pytest.raises(ValueError, match="confirm-one-way"):
            await run_enable_crs(robot, confirm_one_way=False)


@pytest.mark.asyncio
@respx.mock
async def test_run_enable_crs_happy_path() -> None:
    base = "http://192.168.0.21:31950"
    respx.get(f"{base}/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": False}})
    )

    def _create_user_response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        username = body["data"]["username"]
        account_type = body["data"]["accountType"]
        return httpx.Response(
            201,
            json=_user_json(username, account_type=account_type),
        )

    respx.post(f"{base}/auth/users").mock(side_effect=_create_user_response)
    respx.patch(f"{base}/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": True}})
    )
    _mock_oauth_and_idle_logout(base)
    for username in (
        "flex_test_admin",
        "flex_test_operator",
        "flex_test_auditor",
        "flex_test_service",
    ):
        respx.get(f"{base}/auth/users/byUsername/{username}").mock(
            return_value=httpx.Response(404, json={"errors": []})
        )

    settings = _settings()
    async with FlexRobot(settings) as robot:
        result = await run_enable_crs(robot, confirm_one_way=True)

    assert result.bootstrap_username == "flex_harness_admin"
    assert result.bootstrap_created is True
    assert result.crs_enabled is True
    assert result.provision.fail_count == 0
    assert result.idle_logout_seconds == HARNESS_IDLE_LOGOUT_SECONDS
    patch_calls = [call for call in respx.calls if call.request.method == "PATCH"]
    assert len(patch_calls) == 2
    assert any(
        "/auth/settings/accessControlEnabled" in str(call.request.url)
        for call in patch_calls
    )
    assert any(call.request.url.path == "/auth/settings" for call in patch_calls)


@pytest.mark.asyncio
@respx.mock
async def test_run_enable_crs_already_enabled_skips_idle_patch_when_set() -> None:
    base = "http://192.168.0.21:31950"
    respx.get(f"{base}/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": True}})
    )
    respx.post(f"{base}/auth/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "bootstrap-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )
    respx.get(f"{base}/auth/settings").mock(
        return_value=httpx.Response(
            200,
            json=_auth_settings_json(idle_logout=HARNESS_IDLE_LOGOUT_SECONDS),
        )
    )
    for username in (
        "flex_test_admin",
        "flex_test_operator",
        "flex_test_auditor",
        "flex_test_service",
        "flex_backup_admin",
    ):
        respx.get(f"{base}/auth/users/byUsername/{username}").mock(
            return_value=httpx.Response(
                200,
                json=_user_json(username, account_type="admin"),
            )
        )

    settings = _settings()
    async with FlexRobot(settings) as robot:
        result = await run_enable_crs(robot, confirm_one_way=True)

    assert result.crs_enabled is True
    assert result.bootstrap_created is False
    assert result.idle_logout_seconds == HARNESS_IDLE_LOGOUT_SECONDS
    patch_calls = [call for call in respx.calls if call.request.method == "PATCH"]
    assert not patch_calls
