"""Unit tests for CRS auth settings behavior suite."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.crs_auth_settings_suite import (
    parse_case_ids,
    resolve_selected_cases,
    run_auth_settings_suite,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.auth_settings import AuthSettingsData

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


@pytest.mark.unit
def test_parse_case_ids() -> None:
    assert parse_case_ids("S1,S7") == frozenset({"S1", "S7"})
    with pytest.raises(ValueError, match="Unknown case ids"):
        parse_case_ids("S99")


@pytest.mark.unit
def test_resolve_selected_cases_defaults() -> None:
    selected = resolve_selected_cases(cases=None, include_slow=False)
    assert "S0" in selected
    assert "S5" not in selected
    assert "S6" not in selected
    assert "S7" in selected


@pytest.mark.unit
def test_resolve_selected_cases_include_slow() -> None:
    selected = resolve_selected_cases(cases=None, include_slow=True)
    assert "S6" in selected
    assert "S5" not in selected


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_settings_suite_s0_only(tmp_path: Path) -> None:
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
    respx.patch(f"{_BASE}/auth/settings").mock(
        return_value=httpx.Response(
            200,
            json={"data": _SETTINGS.model_dump(by_alias=True)},
        )
    )

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
            cases=frozenset({"S0"}),
            restore_defaults=True,
        )

    assert result.fail_count == 0
    assert any(step.case_id == "S0" for step in result.steps)
    assert any(step.case_id == "cleanup" for step in result.steps)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_settings_suite_blocked_without_mutations(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    from flex_testing_agent.orchestration.gates import MutationDeniedError

    with pytest.raises(MutationDeniedError):
        await run_auth_settings_suite(settings, cases=frozenset({"S0"}))
