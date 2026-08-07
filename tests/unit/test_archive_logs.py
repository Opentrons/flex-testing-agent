"""Unit tests for diagnostic logs client and archive capability."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.archive_logs import archive_diagnostic_logs
from flex_testing_agent.clients.logs import (
    LogsClient,
    discover_log_identifiers,
    identifier_from_log_path,
    normalize_log_identifier,
)
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.robots.flex import FlexRobot


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/logs/api.log", "api.log"),
        ("api.log", "api.log"),
        ("/logs/server.log", "server.log"),
        ("", None),
        ("  ", None),
    ],
)
def test_identifier_from_log_path(raw: str, expected: str | None) -> None:
    assert identifier_from_log_path(raw) == expected


@pytest.mark.unit
def test_normalize_log_identifier() -> None:
    assert normalize_log_identifier("/logs/api.log") == "api.log"
    assert normalize_log_identifier("logs/serial.log") == "serial.log"
    assert normalize_log_identifier("server.log") == "server.log"


@pytest.mark.unit
def test_discover_log_identifiers_from_health(
    sample_health_payload: dict[str, object],
) -> None:
    ids = discover_log_identifiers(sample_health_payload, include_defaults=True)
    assert ids == ["api.log", "serial.log", "server.log"]


@pytest.mark.unit
def test_discover_without_defaults_uses_health_only() -> None:
    payload = {
        "logs": ["/logs/can.log"],
        "links": {"oddLog": "/logs/odd.log"},
    }
    ids = discover_log_identifiers(payload, include_defaults=False)
    assert ids == ["can.log", "odd.log"]


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_logs_client_get_and_list(
    sample_health_payload: dict[str, object],
) -> None:
    respx.get("http://127.0.0.1:31950/health").mock(
        return_value=httpx.Response(200, json=sample_health_payload)
    )
    respx.get("http://127.0.0.1:31950/logs/api.log").mock(
        return_value=httpx.Response(
            200, content=b"line1\n", headers={"content-type": "text/plain"}
        )
    )
    async with RobotHttpSession(
        "http://127.0.0.1:31950", timeout_seconds=1.0
    ) as session:
        client = LogsClient(session)
        ids = await client.list_identifiers()
        assert "api.log" in ids
        content, ctype = await client.get_log("api.log")
        assert content == b"line1\n"
        assert ctype is not None
        assert "text" in ctype


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_try_get_log_soft_404() -> None:
    respx.get("http://127.0.0.1:31950/logs/missing.log").mock(
        return_value=httpx.Response(404, text="missing")
    )
    async with RobotHttpSession(
        "http://127.0.0.1:31950", timeout_seconds=1.0
    ) as session:
        status, content, ctype = await LogsClient(session).try_get_log("missing.log")
    assert status == 404
    assert content is None
    assert ctype is None


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_archive_diagnostic_logs(
    settings: Settings,
    sample_health_payload: dict[str, object],
    tmp_artifacts: Path,
) -> None:
    respx.get("http://127.0.0.1:31950/health").mock(
        return_value=httpx.Response(200, json=sample_health_payload)
    )
    respx.get("http://127.0.0.1:31950/logs/api.log").mock(
        return_value=httpx.Response(200, content=b"api-body")
    )
    respx.get("http://127.0.0.1:31950/logs/serial.log").mock(
        return_value=httpx.Response(200, content=b"serial-body")
    )
    respx.get("http://127.0.0.1:31950/logs/server.log").mock(
        return_value=httpx.Response(404, text="gone")
    )

    dest = tmp_artifacts / "logs" / "test-archive"
    async with FlexRobot(settings) as robot:
        result = await archive_diagnostic_logs(
            robot,
            identifiers=["api.log", "serial.log", "server.log"],
            destination=dest,
        )

    assert result.downloaded == 2
    assert result.skipped == 1
    assert (dest / "api.log").read_bytes() == b"api-body"
    assert (dest / "serial.log").read_bytes() == b"serial-body"
    assert not (dest / "server.log").exists()
    assert result.manifest_path.is_file()
    manifest_text = result.manifest_path.read_text(encoding="utf-8")
    assert "api.log" in manifest_text
    assert result.system_version == "2026.1.0"
