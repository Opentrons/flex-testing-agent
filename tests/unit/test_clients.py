"""Mocked client tests."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.clients.auth_settings import AuthSettingsClient
from flex_testing_agent.clients.errors import RobotApiError, RobotTimeoutError
from flex_testing_agent.clients.health import HealthClient
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.clients.update_health import UpdateHealthClient
from flex_testing_agent.models.access_control import AccessControlState


@pytest.fixture
async def session() -> RobotHttpSession:
    client = RobotHttpSession("http://127.0.0.1:31950", timeout_seconds=1.0)
    yield client
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_health_client(
    session: RobotHttpSession,
    sample_health_payload: dict[str, object],
) -> None:
    respx.get("http://127.0.0.1:31950/health").mock(
        return_value=httpx.Response(200, json=sample_health_payload)
    )
    report = await HealthClient(session).get_health()
    assert report.name == "Kansas"
    assert report.system_version == "2026.1.0"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_update_health_client(
    session: RobotHttpSession,
    sample_update_health_payload: dict[str, object],
) -> None:
    respx.get("http://127.0.0.1:31950/server/update/health").mock(
        return_value=httpx.Response(200, json=sample_update_health_payload)
    )
    report = await UpdateHealthClient(session).get_update_health()
    assert report.update_server_version == "8.5.0"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_access_control_disabled(session: RobotHttpSession) -> None:
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": False}})
    )
    status = await AuthSettingsClient(session).detect_access_control()
    assert status.state == AccessControlState.DISABLED
    assert status.raw_enabled is False


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_access_control_unsupported(session: RobotHttpSession) -> None:
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(404, text="not found")
    )
    status = await AuthSettingsClient(session).detect_access_control()
    assert status.state == AccessControlState.UNSUPPORTED


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_access_control_unknown_on_error(session: RobotHttpSession) -> None:
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(500, text="boom")
    )
    status = await AuthSettingsClient(session).detect_access_control()
    assert status.state == AccessControlState.UNKNOWN


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_timeout_raises(session: RobotHttpSession) -> None:
    respx.get("http://127.0.0.1:31950/health").mock(
        side_effect=httpx.TimeoutException("slow")
    )
    with pytest.raises(RobotTimeoutError):
        await HealthClient(session).get_health()


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_http_error_raises(session: RobotHttpSession) -> None:
    respx.get("http://127.0.0.1:31950/health").mock(
        return_value=httpx.Response(503, text="not ready")
    )
    with pytest.raises(RobotApiError) as exc:
        await HealthClient(session).get_health()
    assert exc.value.status_code == 503


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_omits_authorization_without_token() -> None:
    session = RobotHttpSession("http://127.0.0.1:31950")
    assert "Authorization" not in session._client.headers
    await session.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_includes_bearer_when_token_set() -> None:
    session = RobotHttpSession("http://127.0.0.1:31950", access_token="abc")
    assert session._client.headers["Authorization"] == "Bearer abc"
    await session.aclose()
