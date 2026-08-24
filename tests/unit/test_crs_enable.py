"""Unit tests for CRS enable capability."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.crs_on import run_enable_crs
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


def _settings() -> Settings:
    return Settings(
        robot_host="192.168.0.21",
        allow_mutations=True,
        # Isolate from lab .env CRS_ADMIN_* overrides.
        crs_admin_username=None,
        crs_admin_password=None,
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
    patch_calls = [call for call in respx.calls if call.request.method == "PATCH"]
    assert patch_calls
