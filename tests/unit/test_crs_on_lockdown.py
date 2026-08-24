"""Unit tests for CRS-on lockdown catalog and evaluation helpers."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.crs_on_lockdown import (
    LockdownActor,
    LockdownProbeResult,
    LockdownSuiteResult,
    _evaluate_probe,
    _expectation_for_actor,
    probe_plaintext_http_closed,
)
from flex_testing_agent.catalog.crs_on_lockdown import (
    endpoints_for_crs_on_lockdown,
    is_lockdown_probe_safe,
    is_public_when_crs_on,
    resolve_lockdown_path,
    unauthenticated_should_deny,
)
from flex_testing_agent.catalog.endpoints import (
    FLEX_HTTP_ENDPOINTS,
    ApiService,
    EndpointSpec,
    HttpMethod,
)
from flex_testing_agent.clients.http_probe import HttpStatusProbe
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.risk import RiskLevel


def _spec(
    name: str,
    *,
    method: HttpMethod = HttpMethod.GET,
    path: str = "/example",
    service: ApiService = ApiService.ROBOT_SERVER,
    scopes: tuple[str, ...] = ("run_data.write",),
) -> EndpointSpec:
    return EndpointSpec(
        name=name,
        method=method,
        path=path,
        service=service,
        group="test",
        risk_level=RiskLevel.READ_ONLY,
        required_scopes=scopes,
    )


def test_unauthenticated_should_deny_mutations_only() -> None:
    health = _spec("get_health", path="/health", scopes=())
    runs = _spec("get_runs", path="/runs", scopes=("run_data.write",))
    post_runs = _spec(
        "post_runs",
        method=HttpMethod.POST,
        path="/runs",
        scopes=("run_data.write",),
    )
    assert not unauthenticated_should_deny(health)
    assert not unauthenticated_should_deny(runs)
    assert unauthenticated_should_deny(post_runs)


def test_client_data_is_public_when_crs_on() -> None:
    """RQA-5918: /clientData is App/ODD coordination, not under CRS."""
    names = {
        "get_clientData_key",
        "put_clientData_key",
        "delete_clientData_key",
        "delete_clientData",
    }
    specs = [ep for ep in FLEX_HTTP_ENDPOINTS if ep.name in names]
    assert {ep.name for ep in specs} == names
    for spec in specs:
        assert is_public_when_crs_on(spec)
        assert not unauthenticated_should_deny(spec)
        assert _expectation_for_actor(spec, LockdownActor.NONE) == "public_ok"
        assert _expectation_for_actor(spec, LockdownActor.BAD_BEARER) == "public_ok"
        malformed = LockdownActor.MALFORMED_BEARER
        assert _expectation_for_actor(spec, malformed) == "public_ok"
        assert _expectation_for_actor(spec, LockdownActor.AUDITOR) is None


def test_resolve_lockdown_path_substitutes_placeholders() -> None:
    resolved = resolve_lockdown_path("/runs/{runId}/commands/{commandId}")
    assert resolved is not None
    assert "{runId}" not in resolved
    assert "{commandId}" not in resolved


def test_endpoints_for_crs_on_lockdown_parameter_free_subset() -> None:
    all_eps = endpoints_for_crs_on_lockdown(include_parameterized=False)
    with_params = endpoints_for_crs_on_lockdown(include_parameterized=True)
    assert len(with_params) >= len(all_eps)
    assert all(not ep.parameterized for ep in all_eps)


def test_evaluate_probe_deny_strict_auth_server_mutation() -> None:
    spec = _spec(
        "patch_auth_settings",
        method=HttpMethod.PATCH,
        path="/auth/settings",
        service=ApiService.AUTH_SERVER,
        scopes=("auth_settings.write",),
    )
    deny = _evaluate_probe(
        spec,
        actor=LockdownActor.NONE,
        expected="deny",
        probe=HttpStatusProbe(401, 0, False, "application/json"),
        strict=True,
    )
    assert deny.ok
    leak = _evaluate_probe(
        spec,
        actor=LockdownActor.NONE,
        expected="deny",
        probe=HttpStatusProbe(200, 100, True, "application/json"),
        strict=True,
    )
    assert not leak.ok
    assert leak.body_has_data


def test_evaluate_probe_get_public_ok_without_auth() -> None:
    spec = _spec(
        "get_auth_settings",
        path="/auth/settings",
        service=ApiService.AUTH_SERVER,
        scopes=("auth_settings.read",),
    )
    row = _evaluate_probe(
        spec,
        actor=LockdownActor.NONE,
        expected="public_ok",
        probe=HttpStatusProbe(200, 100, True, "application/json"),
        strict=True,
    )
    assert row.ok


def test_evaluate_probe_robot_server_get_404_ok() -> None:
    spec = _spec("get_runs_runId", path="/runs/{runId}")
    row = _evaluate_probe(
        spec,
        actor=LockdownActor.NONE,
        expected="public_ok",
        probe=HttpStatusProbe(404, 0, False, "application/json"),
        strict=False,
    )
    assert row.ok


def test_expectation_auditor_denies_mutations() -> None:
    post = _spec(
        "post_runs",
        method=HttpMethod.POST,
        path="/runs",
        scopes=("run_data.write",),
    )
    assert _expectation_for_actor(post, LockdownActor.AUDITOR) == "deny"


def test_lockdown_excludes_disruptive_restart() -> None:
    restart = EndpointSpec(
        name="post_server_restart",
        method=HttpMethod.POST,
        path="/server/restart",
        service=ApiService.UPDATE_SERVER,
        group="update",
        risk_level=RiskLevel.DISRUPTIVE,
    )
    assert not is_lockdown_probe_safe(restart)
    names = {
        ep.name for ep in endpoints_for_crs_on_lockdown(include_parameterized=True)
    }
    assert "post_server_restart" not in names
    assert "post_server_shutdown" not in names


def test_expectation_operator_skips_allowed_routes() -> None:
    """Lockdown skips authed probes that would expect success (no live mutations)."""
    restart = EndpointSpec(
        name="post_server_restart",
        method=HttpMethod.POST,
        path="/server/restart",
        service=ApiService.UPDATE_SERVER,
        group="update",
        risk_level=RiskLevel.DISRUPTIVE,
    )
    assert _expectation_for_actor(restart, LockdownActor.OPERATOR) is None
    health = _spec("get_health", path="/health", scopes=())
    assert _expectation_for_actor(health, LockdownActor.OPERATOR) is None
    assert _expectation_for_actor(health, LockdownActor.NONE) == "public_ok"


@pytest.mark.asyncio
@respx.mock
async def test_plaintext_http_open_fails() -> None:
    settings = Settings(
        robot_host="192.168.0.21",
        robot_use_https=True,
        robot_http_port=31950,
        robot_health_timeout_seconds=1.0,
    )
    respx.get("http://192.168.0.21:31950/health").mock(
        return_value=httpx.Response(200, json={"name": "KansasFLEX"})
    )
    respx.post("http://192.168.0.21:31950/auth/oauth2/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    rows = await probe_plaintext_http_closed(settings)
    assert len(rows) == 2
    assert all(not row.ok for row in rows)
    assert {row.endpoint for row in rows} == {
        "plaintext_http_health",
        "plaintext_http_oauth",
    }


@pytest.mark.asyncio
@respx.mock
async def test_plaintext_http_closed_passes() -> None:
    settings = Settings(
        robot_host="192.168.0.21",
        robot_use_https=True,
        robot_http_port=31950,
        robot_health_timeout_seconds=1.0,
    )
    respx.get("http://192.168.0.21:31950/health").mock(
        side_effect=httpx.ConnectError("closed")
    )
    respx.post("http://192.168.0.21:31950/auth/oauth2/token").mock(
        side_effect=httpx.ConnectError("closed")
    )
    rows = await probe_plaintext_http_closed(settings)
    assert len(rows) == 2
    assert all(row.ok for row in rows)
    assert all(row.status_code is None for row in rows)


def test_plaintext_http_is_hard_failure() -> None:
    result = LockdownSuiteResult(
        results=[
            LockdownProbeResult(
                endpoint="plaintext_http_health",
                method="GET",
                path="/health",
                actor="plaintext_http",
                expected="deny",
                status_code=200,
                ok=False,
                detail="open",
            )
        ]
    )
    assert result.hard_failures() == result.results
