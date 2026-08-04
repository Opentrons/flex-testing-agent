"""Unit tests for maintenance_runs / labware_offsets clients and LPC seed helpers."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.seed_lpc import (
    DEFAULT_DEFINITION_URI,
    run_seed_lpc_scripted,
)
from flex_testing_agent.capabilities.seed_runs import SeedId, parse_seed_ids
from flex_testing_agent.clients.labware_offsets import LabwareOffsetsClient
from flex_testing_agent.clients.maintenance_runs import MaintenanceRunsClient
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.orchestration.timing import TimingSession
from flex_testing_agent.robots.flex import FlexRobot


@pytest.fixture
async def session() -> RobotHttpSession:
    client = RobotHttpSession("http://127.0.0.1:31950", timeout_seconds=1.0)
    yield client
    await client.aclose()


@pytest.mark.unit
def test_parse_seed_ids_includes_lpc_scripted() -> None:
    assert parse_seed_ids(["lpc-scripted"]) == [SeedId.LPC_SCRIPTED]


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_maintenance_runs_create_and_command(
    session: RobotHttpSession,
) -> None:
    respx.post("http://127.0.0.1:31950/maintenance_runs").mock(
        return_value=httpx.Response(201, json={"data": {"id": "mr1", "status": "idle"}})
    )
    respx.post(
        url__regex=r"http://127\.0\.0\.1:31950/maintenance_runs/mr1/commands\?.*"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "data": {
                    "id": "c1",
                    "commandType": "home",
                    "status": "succeeded",
                }
            },
        )
    )
    respx.delete("http://127.0.0.1:31950/maintenance_runs/mr1").mock(
        return_value=httpx.Response(200, json={"data": {"id": "mr1"}})
    )
    client = MaintenanceRunsClient(session)
    created = await client.create()
    assert client.run_id_from_create(created) == "mr1"
    cmd = await client.enqueue_command(
        "mr1",
        {"commandType": "home", "params": {}},
        timeout_ms=5_000,
    )
    assert client.command_status(cmd) == "succeeded"
    await client.delete("mr1")


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_labware_offsets_create_and_list(
    session: RobotHttpSession,
) -> None:
    respx.post("http://127.0.0.1:31950/labwareOffsets").mock(
        return_value=httpx.Response(
            201,
            json={
                "data": {
                    "id": "off1",
                    "definitionUri": DEFAULT_DEFINITION_URI,
                    "vector": {"x": 0.1, "y": 0.0, "z": 0.0},
                }
            },
        )
    )
    respx.get("http://127.0.0.1:31950/labwareOffsets").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "off1", "definitionUri": DEFAULT_DEFINITION_URI}]},
        )
    )
    client = LabwareOffsetsClient(session)
    created = await client.create_offset(
        {
            "definitionUri": DEFAULT_DEFINITION_URI,
            "locationSequence": [
                {"kind": "onAddressableArea", "addressableAreaName": "C2"},
            ],
            "vector": {"x": 0.1, "y": 0.0, "z": 0.0},
        }
    )
    assert client.offset_id_from_create(created) == "off1"
    listed = await client.list_offset_summaries()
    assert listed[0]["id"] == "off1"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_seed_lpc_scripted_happy_path(tmp_path: Path) -> None:
    base = "http://127.0.0.1:31950"
    respx.get(f"{base}/maintenance_runs/current_run").mock(
        return_value=httpx.Response(404, json={"errors": [{"detail": "none"}]})
    )
    respx.post(f"{base}/maintenance_runs").mock(
        return_value=httpx.Response(201, json={"data": {"id": "mr-lpc"}})
    )
    respx.post(url__regex=rf"{base}/maintenance_runs/mr-lpc/commands\?.*").mock(
        return_value=httpx.Response(
            201,
            json={"data": {"id": "c", "status": "succeeded", "commandType": "home"}},
        )
    )
    respx.post(f"{base}/labwareOffsets").mock(
        return_value=httpx.Response(
            201,
            json={"data": {"id": "offset-1", "definitionUri": DEFAULT_DEFINITION_URI}},
        )
    )
    respx.get(f"{base}/maintenance_runs/mr-lpc").mock(
        return_value=httpx.Response(200, json={"data": {"id": "mr-lpc"}})
    )
    respx.delete(f"{base}/maintenance_runs/mr-lpc").mock(
        return_value=httpx.Response(200, json={"data": {"id": "mr-lpc"}})
    )

    settings = Settings(
        robot_host="127.0.0.1",
        robot_name="test",
        allow_mutations=True,
        artifact_directory=tmp_path,
    )
    async with FlexRobot(settings) as robot:
        timing = TimingSession(label="test-lpc", robot_host="127.0.0.1")
        result = await run_seed_lpc_scripted(robot, timing)

    assert result.ok is True
    assert result.maintenance_run_id == "mr-lpc"
    assert result.offset_id == "offset-1"
    assert "loadPipette" in result.commands
    assert "savePosition" in result.commands
