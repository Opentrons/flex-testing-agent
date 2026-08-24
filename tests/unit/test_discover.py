"""Unit tests for multi-IP robot host discovery."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.orchestration.discover import (
    CrsHttpsRequiredError,
    RobotDiscoveryError,
    describe_crs_https_upgrade,
    resolve_robot_host,
    settings_with_resolved_host,
)
from flex_testing_agent.robot_certs.registry import RobotCertRegistryError


@pytest.mark.unit
def test_candidate_hosts_prefers_robot_host() -> None:
    settings = Settings(
        robot_host="192.168.0.99",
        robot_host_candidates="192.168.0.21,192.168.0.20",
    )
    assert settings.candidate_hosts() == [
        "192.168.0.99",
        "192.168.0.21",
        "192.168.0.20",
    ]


@pytest.mark.unit
def test_candidate_hosts_dedupes_primary() -> None:
    settings = Settings(
        robot_host="192.168.0.21",
        robot_host_candidates="192.168.0.21,192.168.0.20",
    )
    assert settings.candidate_hosts() == ["192.168.0.21", "192.168.0.20"]


@pytest.mark.unit
def test_require_robot_host_uses_candidates_when_primary_empty() -> None:
    settings = Settings(
        robot_host="",
        robot_host_candidates="192.168.0.21,192.168.0.20",
    )
    assert settings.require_robot_host() == "192.168.0.21"


@pytest.mark.unit
def test_require_robot_host_raises_when_no_candidates() -> None:
    settings = Settings(robot_host="", robot_host_candidates="")
    with pytest.raises(ValueError, match="ROBOT_HOST"):
        settings.require_robot_host()


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_resolve_skips_dead_primary_and_uses_candidate() -> None:
    settings = Settings(
        robot_host="192.168.0.20",
        robot_host_candidates="192.168.0.21,192.168.0.20",
        robot_name="KansasFLEX",
        robot_http_port=31950,
        robot_health_timeout_seconds=1.0,
    )
    respx.get("http://192.168.0.20:31950/health").mock(
        side_effect=httpx.ConnectTimeout("timeout")
    )
    respx.get("http://192.168.0.21:31950/health").mock(
        return_value=httpx.Response(
            200,
            json={"name": "KansasFLEX", "system_version": "ot3@4.0.0-alpha.10"},
        )
    )
    respx.get("http://192.168.0.21:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": False}})
    )
    assert await resolve_robot_host(settings) == "192.168.0.21"
    resolved = await settings_with_resolved_host(settings)
    assert resolved.robot_host == "192.168.0.21"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_resolve_rejects_wrong_robot_name() -> None:
    settings = Settings(
        robot_host="192.168.0.21",
        robot_host_candidates="",
        robot_name="KansasFLEX",
        robot_http_port=31950,
        robot_health_timeout_seconds=1.0,
    )
    respx.get("http://192.168.0.21:31950/health").mock(
        return_value=httpx.Response(200, json={"name": "OtherFLEX"})
    )
    with pytest.raises(RobotDiscoveryError, match="No reachable Flex"):
        await resolve_robot_host(settings)


_HEALTH = {"name": "KansasFLEX", "system_version": "ot3@10.0.0-alpha.4"}


def _http_settings() -> Settings:
    return Settings(
        robot_host="192.168.0.21",
        robot_host_candidates="",
        robot_name="KansasFLEX",
        robot_http_port=31950,
        robot_https_port=32313,
        robot_use_https=False,
        robot_health_timeout_seconds=1.0,
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_settings_stays_http_when_crs_off() -> None:
    settings = _http_settings()
    respx.get("http://192.168.0.21:31950/health").mock(
        return_value=httpx.Response(200, json=_HEALTH)
    )
    respx.get("http://192.168.0.21:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": False}})
    )
    resolved = await settings_with_resolved_host(settings)
    assert resolved.robot_use_https is False
    assert resolved.robot_base_url == "http://192.168.0.21:31950"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_settings_forces_https_when_crs_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _http_settings()
    monkeypatch.setattr(
        "flex_testing_agent.orchestration.discover.resolve_httpx_verify",
        lambda _settings, *, host: True,
    )
    respx.get("http://192.168.0.21:31950/health").mock(
        return_value=httpx.Response(200, json=_HEALTH)
    )
    respx.get("http://192.168.0.21:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": True}})
    )
    resolved = await settings_with_resolved_host(settings)
    assert resolved.robot_use_https is True
    assert resolved.robot_base_url == "https://192.168.0.21:32313"
    note = describe_crs_https_upgrade(settings, resolved)
    assert note is not None
    assert "HTTPS" in note


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_settings_crs_on_without_ca_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _http_settings()

    def _no_ca(_settings: Settings, *, host: str) -> bool:
        raise RobotCertRegistryError("No CA certificate")

    monkeypatch.setattr(
        "flex_testing_agent.orchestration.discover.resolve_httpx_verify",
        _no_ca,
    )
    respx.get("http://192.168.0.21:31950/health").mock(
        return_value=httpx.Response(200, json=_HEALTH)
    )
    respx.get("http://192.168.0.21:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": True}})
    )
    with pytest.raises(CrsHttpsRequiredError, match="trust-ca"):
        await settings_with_resolved_host(settings)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_settings_https_fallback_when_http_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _http_settings()
    monkeypatch.setattr(
        "flex_testing_agent.orchestration.discover.resolve_httpx_verify",
        lambda _settings, *, host: True,
    )
    respx.get("http://192.168.0.21:31950/health").mock(
        side_effect=httpx.ConnectError("closed")
    )
    respx.get("https://192.168.0.21:32313/health").mock(
        return_value=httpx.Response(200, json=_HEALTH)
    )
    resolved = await settings_with_resolved_host(settings)
    assert resolved.robot_use_https is True
    assert resolved.robot_host == "192.168.0.21"
