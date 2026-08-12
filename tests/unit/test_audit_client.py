"""Unit tests for audit-server client."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.clients.audit import AuditClient
from flex_testing_agent.clients.session import RobotHttpSession


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_list_log_periods() -> None:
    respx.get("http://192.168.0.21:31950/audit/external/logPeriods").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": 1,
                        "startedAt": "2026-08-11T18:00:00Z",
                        "endedAt": "2026-08-11T19:00:00Z",
                    },
                    {
                        "id": "2",
                        "startedAt": "2026-08-11T19:00:00Z",
                        "endedAt": None,
                    },
                ],
                "meta": {"cursor": 0, "totalLength": 2},
            },
        )
    )
    async with RobotHttpSession("http://192.168.0.21:31950") as session:
        periods = await AuditClient(session).list_log_periods()
    assert len(periods) == 2
    assert periods[0].id == "1"
    assert periods[0].ended_at == "2026-08-11T19:00:00Z"
    assert periods[1].id == "2"
    assert periods[1].ended_at is None


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_download_log_period() -> None:
    respx.get("http://192.168.0.21:31950/audit/external/logPeriods/7/download").mock(
        return_value=httpx.Response(
            200,
            content=b"PK\x03\x04fake-zip",
            headers={"content-type": "application/zip"},
        )
    )
    async with RobotHttpSession("http://192.168.0.21:31950") as session:
        downloaded = await AuditClient(session).download_log_period(7)
    assert downloaded.period_id == "7"
    assert downloaded.content.startswith(b"PK")
    assert downloaded.content_type == "application/zip"
