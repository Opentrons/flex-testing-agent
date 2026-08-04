"""Unit tests for multi-IP robot host discovery."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.orchestration.discover import (
    RobotDiscoveryError,
    resolve_robot_host,
    settings_with_resolved_host,
)


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
