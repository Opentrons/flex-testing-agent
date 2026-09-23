"""Unit tests for protocol analysis CRS behavior (RQA-6012)."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.protocol_analysis_suite import (
    _probe_create_analysis,
)
from flex_testing_agent.clients.protocols import ProtocolsClient
from flex_testing_agent.clients.session import RobotHttpSession


@pytest.fixture
async def session() -> RobotHttpSession:
    client = RobotHttpSession("http://127.0.0.1:31950", timeout_seconds=1.0)
    yield client
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_probe_create_analysis_success(session: RobotHttpSession) -> None:
    respx.post("http://127.0.0.1:31950/protocols/p1/analyses").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "a1", "status": "pending"}]},
        )
    )
    probe = await _probe_create_analysis(
        ProtocolsClient(session),
        "p1",
        step="reanalysis_unauthenticated_altered_rtps",
        run_time_parameter_values={"num_sample": 48, "dry_run": True},
    )
    assert probe.http_status == 200
    assert probe.step == "reanalysis_unauthenticated_altered_rtps"
    assert "num_sample" in probe.detail


@pytest.mark.asyncio
@respx.mock
async def test_probe_create_analysis_451_documentation_required(
    session: RobotHttpSession,
) -> None:
    respx.post("http://127.0.0.1:31950/protocols/p1/analyses").mock(
        return_value=httpx.Response(
            451,
            json={"errors": [{"detail": "documentation required"}]},
        )
    )
    probe = await _probe_create_analysis(
        ProtocolsClient(session),
        "p1",
        step="reanalysis_authenticated_no_notes_altered_rtps",
        run_time_parameter_values={"num_sample": 24},
    )
    assert probe.http_status == 451
    assert "documentation" in probe.detail.lower()


@pytest.mark.asyncio
@respx.mock
async def test_probe_create_analysis_401_unauthenticated(
    session: RobotHttpSession,
) -> None:
    respx.post("http://127.0.0.1:31950/protocols/p1/analyses").mock(
        return_value=httpx.Response(401, json={"errors": [{"detail": "unauthorized"}]})
    )
    probe = await _probe_create_analysis(
        ProtocolsClient(session),
        "p1",
        step="reanalysis_unauthenticated_altered_rtps",
        run_time_parameter_values={"num_sample": 48},
    )
    assert probe.http_status == 401
