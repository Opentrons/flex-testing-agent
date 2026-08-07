"""Unit tests for CRS-on Tier B."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.crs_on_tier_b import run_crs_on_tier_b
from flex_testing_agent.config.settings import Settings


def _mock_crs_on_auth() -> None:
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": True}})
    )
    respx.post("http://127.0.0.1:31950/auth/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "test-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )


def _mock_extra_tier_b_fixture_gets() -> None:
    respx.get("http://127.0.0.1:31950/subsystems/status").mock(
        return_value=httpx.Response(
            200, json={"data": [{"name": "gantry_x", "fw_update_needed": False}]}
        )
    )
    respx.get("http://127.0.0.1:31950/subsystems/updates/all").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "upd-1"}]})
    )
    respx.get("http://127.0.0.1:31950/subsystems/updates/current").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get("http://127.0.0.1:31950/instruments").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get("http://127.0.0.1:31950/clientData").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get("http://127.0.0.1:31950/logs").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get("http://127.0.0.1:31950/maintenance_runs").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get("http://127.0.0.1:31950/commands").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get("http://127.0.0.1:31950/calibrations").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get("http://127.0.0.1:31950/system/update/status").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )


def _mock_crs_off_auth() -> None:
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": False}})
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_crs_on_tier_b_uses_auth_username_fixture(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    _mock_crs_on_auth()
    respx.get("http://127.0.0.1:31950/protocols").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "p1"}]})
    )
    respx.get("http://127.0.0.1:31950/protocols/p1/analyses").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "a1"}]})
    )
    respx.get("http://127.0.0.1:31950/runs").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"id": "r1", "current": True, "status": "idle"}],
                "links": {"current": {"href": "/runs/r1"}},
            },
        )
    )
    respx.get("http://127.0.0.1:31950/runs/r1/commands").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "c1"}]})
    )
    respx.get("http://127.0.0.1:31950/dataFiles").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "df1"}]})
    )
    _mock_extra_tier_b_fixture_gets()
    respx.get(url__regex=r"http://127\.0\.0\.1:31950/.*").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )

    result = await run_crs_on_tier_b(
        settings,
        username="flex_test_operator",
        create_fixtures=False,
    )

    assert result.fixtures["protocol_id"] == "p1"
    assert result.fixtures["run_id"] == "r1"
    assert result.fixtures["username"] == "flex_test_operator"
    assert result.ok_count >= 1


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_crs_on_tier_b_refuses_when_crs_off(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    _mock_crs_off_auth()
    respx.post("http://127.0.0.1:31950/auth/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "test-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )

    with pytest.raises(RuntimeError, match="CRS / access control is not enabled"):
        await run_crs_on_tier_b(settings, username="flex_test_operator")
