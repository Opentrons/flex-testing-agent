"""Unit tests for AuthSettingsClient policy endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.clients.auth_settings import AuthSettingsClient
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.models.auth_settings import AuthSettingsPatch

_BASE = "http://127.0.0.1:31950"

_SETTINGS_BODY = {
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


@pytest.fixture
async def session() -> RobotHttpSession:
    client = RobotHttpSession(_BASE, timeout_seconds=1.0)
    yield client
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_get_settings(session: RobotHttpSession) -> None:
    respx.get(f"{_BASE}/auth/settings").mock(
        return_value=httpx.Response(200, json=_SETTINGS_BODY)
    )
    settings = await AuthSettingsClient(session).get_settings()
    assert settings.max_number_of_login_attempts == 5
    assert settings.idle_logout == 180.0


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_patch_settings(session: RobotHttpSession) -> None:
    route = respx.patch(f"{_BASE}/auth/settings").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    **_SETTINGS_BODY["data"],
                    "maxNumberOfLoginAttempts": 3,
                }
            },
        )
    )
    updated = await AuthSettingsClient(session).patch_settings(
        AuthSettingsPatch(max_number_of_login_attempts=3)
    )
    assert updated.max_number_of_login_attempts == 3
    assert route.called
    request = route.calls.last.request
    assert request.content is not None
    assert b"maxNumberOfLoginAttempts" in request.content


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_delete_settings(session: RobotHttpSession) -> None:
    respx.delete(f"{_BASE}/auth/settings").mock(return_value=httpx.Response(204))
    respx.get(f"{_BASE}/auth/settings").mock(
        return_value=httpx.Response(200, json=_SETTINGS_BODY)
    )
    settings = await AuthSettingsClient(session).delete_settings()
    assert settings.require_admin_creds_for_signoff_protocol is False
