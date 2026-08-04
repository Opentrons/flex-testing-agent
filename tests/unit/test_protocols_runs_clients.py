"""Unit tests for protocols / runs / data-files / CRS-off suite helpers."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.crs_off import (
    _Fixtures,
    _resolve_path,
    run_crs_off_tier_b,
    run_crs_off_tier_c,
)
from flex_testing_agent.clients.data_files import DataFilesClient
from flex_testing_agent.clients.protocols import ProtocolsClient
from flex_testing_agent.clients.runs import RunsClient
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.orchestration.gates import MutationDeniedError
from flex_testing_agent.robots.flex import FlexRobot


@pytest.fixture
async def session() -> RobotHttpSession:
    client = RobotHttpSession("http://127.0.0.1:31950", timeout_seconds=1.0)
    yield client
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_protocols_list_and_get(session: RobotHttpSession) -> None:
    respx.get("http://127.0.0.1:31950/protocols").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "p1", "metadata": {"protocolName": "x"}}]}
        )
    )
    respx.get("http://127.0.0.1:31950/protocols/p1").mock(
        return_value=httpx.Response(200, json={"data": {"id": "p1"}})
    )
    client = ProtocolsClient(session)
    assert client.list_protocol_summaries  # type check surface
    summaries = await client.list_protocol_summaries()
    assert summaries[0]["id"] == "p1"
    got = await client.get_protocol("p1")
    assert got["data"]["id"] == "p1"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_protocols_upload_multipart(
    session: RobotHttpSession, tmp_path: Path
) -> None:
    protocol = tmp_path / "smoke.py"
    protocol.write_text("metadata={'protocolName':'t'}\n")
    respx.post("http://127.0.0.1:31950/protocols").mock(
        return_value=httpx.Response(201, json={"data": {"id": "uploaded-1"}})
    )
    payload = await ProtocolsClient(session).upload_protocol(protocol)
    assert ProtocolsClient(session).protocol_id_from_upload(payload) == "uploaded-1"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_runs_create_and_get(session: RobotHttpSession) -> None:
    respx.post("http://127.0.0.1:31950/runs").mock(
        return_value=httpx.Response(201, json={"data": {"id": "r1", "status": "idle"}})
    )
    respx.get("http://127.0.0.1:31950/runs/r1/commands").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.patch("http://127.0.0.1:31950/runs/r1").mock(
        return_value=httpx.Response(
            200, json={"data": {"id": "r1", "current": False, "status": "stopped"}}
        )
    )
    client = RunsClient(session)
    created = await client.create_run(protocol_id="p1")
    assert client.run_id_from_create(created) == "r1"
    commands = await client.list_commands("r1")
    assert commands["data"] == []
    uncurrented = await client.set_current("r1", current=False)
    assert uncurrented["data"]["current"] is False


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_data_files_upload_csv(session: RobotHttpSession, tmp_path: Path) -> None:
    csv_path = tmp_path / "samples.csv"
    csv_path.write_text("a,b\n1,2\n")
    respx.post("http://127.0.0.1:31950/dataFiles").mock(
        return_value=httpx.Response(
            201, json={"data": {"id": "df1", "name": "samples.csv"}}
        )
    )
    client = DataFilesClient(session)
    payload = await client.upload_csv(csv_path)
    assert client.data_file_id_from_upload(payload) == "df1"


@pytest.mark.unit
def test_resolve_path_requires_all_params() -> None:
    fixtures = _Fixtures(protocol_id="p1", run_id="r1")
    assert _resolve_path("/protocols/{protocolId}", fixtures) == "/protocols/p1"
    assert _resolve_path("/runs/{runId}/commands/{commandId}", fixtures) is None
    fixtures.command_id = "c1"
    assert (
        _resolve_path("/runs/{runId}/commands/{commandId}", fixtures)
        == "/runs/r1/commands/c1"
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_tier_b_uses_existing_fixtures(
    tmp_path: Path,
) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": False}})
    )
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
    # Accept any remaining parameterized GETs
    respx.get(url__regex=r"http://127\.0\.0\.1:31950/.*").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )

    async with FlexRobot(settings) as robot:
        result = await run_crs_off_tier_b(robot, create_fixtures=False)

    assert result.fixtures["protocol_id"] == "p1"
    assert result.fixtures["run_id"] == "r1"
    assert result.ok_count >= 1
    assert result.fail_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_tier_c_blocked_without_mutations(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": False}})
    )
    async with FlexRobot(settings) as robot:
        with pytest.raises(MutationDeniedError):
            await run_crs_off_tier_c(robot)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_tier_c_lights_and_client_data(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": False}})
    )
    respx.get("http://127.0.0.1:31950/runs").mock(
        return_value=httpx.Response(200, json={"data": [], "links": {}})
    )
    respx.get("http://127.0.0.1:31950/robot/lights").mock(
        return_value=httpx.Response(200, json={"on": False})
    )
    respx.post("http://127.0.0.1:31950/robot/lights").mock(
        side_effect=[
            httpx.Response(200, json={"on": True}),
            httpx.Response(200, json={"on": False}),
        ]
    )
    client_data_body = {"data": {"source": "flex-testing-agent"}}
    respx.put("http://127.0.0.1:31950/clientData/flex-testing-agent-crs-off").mock(
        return_value=httpx.Response(200, json=client_data_body)
    )
    respx.get("http://127.0.0.1:31950/clientData/flex-testing-agent-crs-off").mock(
        return_value=httpx.Response(200, json=client_data_body)
    )
    respx.delete("http://127.0.0.1:31950/clientData/flex-testing-agent-crs-off").mock(
        return_value=httpx.Response(200, json={"data": None})
    )

    async with FlexRobot(settings) as robot:
        result = await run_crs_off_tier_c(robot)

    assert result.fail_count == 0
    assert result.ok_count >= 2
