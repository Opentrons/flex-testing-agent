"""Unit tests for passwordResetTime boundary validation (S5)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.crs_auth_settings_suite import (
    _case_s5,
    run_auth_settings_suite,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.auth_settings import (
    PASSWORD_RESET_TIME_MIN_SECONDS,
    AuthSettingsData,
)
from flex_testing_agent.robots.flex import FlexRobot

_BASE = "http://127.0.0.1:31950"

_SETTINGS = AuthSettingsData.model_validate(
    {
        "maxNumberOfLoginAttempts": 5,
        "passwordResetTime": None,
        "passwordComplexityMinimumLength": None,
        "passwordComplexitySpecialCharacters": None,
        "idleLogout": 180.0,
        "requireAdminCredsWhenUpdatingRobotSoftware": True,
        "requireAdminCredsWhenSendingProtocolToRobot": True,
        "requireAdminCredsForSignoffProtocol": False,
    }
)


def _settings_json(**overrides: object) -> dict[str, dict[str, object]]:
    data = _SETTINGS.model_dump(by_alias=True)
    data.update(overrides)
    return {"data": data}


@pytest.mark.unit
def test_password_reset_time_minimum_constant() -> None:
    assert PASSWORD_RESET_TIME_MIN_SECONDS == 86400


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_case_s5_password_reset_time_boundaries() -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
    )

    def patch_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        value = body["data"].get("passwordResetTime")
        if value is None:
            return httpx.Response(200, json=_settings_json(passwordResetTime=None))
        if float(value) < PASSWORD_RESET_TIME_MIN_SECONDS:
            return httpx.Response(
                422,
                json={
                    "detail": [
                        {
                            "type": "greater_than_equal",
                            "loc": ["body", "data", "passwordResetTime"],
                            "msg": (
                                "Input should be greater than or equal to "
                                f"{PASSWORD_RESET_TIME_MIN_SECONDS}"
                            ),
                            "input": value,
                            "ctx": {"ge": PASSWORD_RESET_TIME_MIN_SECONDS},
                        }
                    ]
                },
            )
        return httpx.Response(200, json=_settings_json(passwordResetTime=value))

    respx.patch(f"{_BASE}/auth/settings").mock(side_effect=patch_handler)

    async with FlexRobot(settings, access_token="admin-tok") as robot:
        detail = await _case_s5(robot, baseline=_SETTINGS)

    minimum = PASSWORD_RESET_TIME_MIN_SECONDS
    assert "422" in detail
    assert "180" in detail
    assert str(minimum) in detail
    assert str(minimum + 1) in detail


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_settings_suite_s5_only(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    respx.get(f"{_BASE}/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"accessControlEnabled": True}},
        )
    )
    respx.get(f"{_BASE}/auth/settings").mock(
        return_value=httpx.Response(
            200,
            json={"data": _SETTINGS.model_dump(by_alias=True)},
        )
    )

    def patch_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        value = body["data"].get("passwordResetTime")
        if value is None:
            return httpx.Response(200, json=_settings_json(passwordResetTime=None))
        if float(value) < PASSWORD_RESET_TIME_MIN_SECONDS:
            return httpx.Response(422, json={"detail": []})
        return httpx.Response(200, json=_settings_json(passwordResetTime=value))

    respx.patch(f"{_BASE}/auth/settings").mock(side_effect=patch_handler)

    protocol = tmp_path / "smoke.py"
    protocol.write_text("# mock protocol")

    with (
        patch(
            "flex_testing_agent.capabilities.crs_auth_settings_suite."
            "access_token_for_username",
            new=AsyncMock(return_value="admin-tok"),
        ),
        patch(
            "flex_testing_agent.capabilities.crs_auth_settings_suite."
            "default_smoke_protocol_path",
            return_value=protocol,
        ),
        patch(
            "flex_testing_agent.capabilities.crs_auth_settings_suite.ensure_crs_on",
            new=AsyncMock(),
        ),
    ):
        result = await run_auth_settings_suite(
            settings,
            cases=frozenset({"S5"}),
            restore_defaults=True,
        )

    s5 = next(step for step in result.steps if step.case_id == "S5")
    assert s5.ok
    assert not s5.skipped
    assert "422" in s5.detail
