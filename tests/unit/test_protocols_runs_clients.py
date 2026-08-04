"""Unit tests for protocols / runs / data-files / CRS-off suite helpers."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.crs_off import (
    CLIENT_DATA_KEY,
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


def _mock_crs_off_auth() -> None:
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": False}})
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
        return_value=httpx.Response(
            200, json={"data": [{"serialNumber": "P50S2023051801"}]}
        )
    )
    respx.get(f"http://127.0.0.1:31950/clientData/{CLIENT_DATA_KEY}").mock(
        return_value=httpx.Response(200, json={"data": {"source": "test"}})
    )


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
    fixtures.command_run_id = "r-hist"
    assert (
        _resolve_path("/runs/{runId}/commands/{commandId}", fixtures)
        == "/runs/r-hist/commands/c1"
    )


@pytest.mark.unit
def test_resolve_path_extra_fixtures() -> None:
    fixtures = _Fixtures(
        protocol_id="p1",
        analysis_id="a1",
        run_id="r1",
        ended_run_id="r0",
        command_run_id="r-hist",
        command_id="c1",
        simple_command_id="sc1",
        maintenance_run_id="m1",
        maintenance_command_id="mc1",
        command_annotation_id="ann1",
        calibration_id="cal1",
        update_session_id="sess1",
        data_file_id="df1",
        client_data_key=CLIENT_DATA_KEY,
        log_identifier="api.log",
        subsystem="gantry_x",
        subsystem_update_id="upd-1",
        pipette_id="P50S2023051801",
        username="flex-testing-agent",
    )
    assert (
        _resolve_path("/clientData/{key}", fixtures) == f"/clientData/{CLIENT_DATA_KEY}"
    )
    assert _resolve_path("/logs/{log_identifier}", fixtures) == "/logs/api.log"
    assert (
        _resolve_path("/subsystems/status/{subsystem}", fixtures)
        == "/subsystems/status/gantry_x"
    )
    assert (
        _resolve_path("/subsystems/updates/all/{id}", fixtures)
        == "/subsystems/updates/all/upd-1"
    )
    assert (
        _resolve_path("/settings/pipettes/{pipette_id}", fixtures)
        == "/settings/pipettes/P50S2023051801"
    )
    assert (
        _resolve_path("/auth/users/byUsername/{username}", fixtures)
        == "/auth/users/byUsername/flex-testing-agent"
    )
    assert (
        _resolve_path("/runs/{runId}/commandsAsPreSerializedList", fixtures)
        == "/runs/r0/commandsAsPreSerializedList"
    )
    assert _resolve_path("/commands/{commandId}", fixtures) == "/commands/sc1"
    assert (
        _resolve_path("/maintenance_runs/{runId}/commands/{commandId}", fixtures)
        == "/maintenance_runs/m1/commands/mc1"
    )
    assert (
        _resolve_path(
            "/runs/{runId}/commandAnnotations/{commandAnnotationId}", fixtures
        )
        == "/runs/r-hist/commandAnnotations/ann1"
    )
    assert (
        _resolve_path("/labware/calibrations/{calibrationId}", fixtures)
        == "/labware/calibrations/cal1"
    )
    assert (
        _resolve_path("/server/update/{session}/status", fixtures)
        == "/server/update/sess1/status"
    )


@pytest.mark.unit
def test_tier_b_preserialized_uses_ended_run_not_current() -> None:
    """commandsAsPreSerializedList must hit an ended run, not current-idle."""
    from flex_testing_agent.catalog import FLEX_HTTP_ENDPOINTS

    fixtures = _Fixtures(run_id="current-idle", ended_run_id="ended-1")
    resolved = _resolve_path(
        "/runs/{runId}/commandsAsPreSerializedList",
        fixtures,
    )
    assert resolved == "/runs/ended-1/commandsAsPreSerializedList"
    assert (
        _resolve_path("/runs/{runId}/commands", fixtures)
        == "/runs/current-idle/commands"
    )
    spec = next(
        s
        for s in FLEX_HTTP_ENDPOINTS
        if s.name == "get_runs_runId_commandsAsPreSerializedList"
    )
    assert 503 not in spec.crs_off_acceptable_status


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_tier_b_preserialized_retries_store_settle_on_ended_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brief 503 after a run ends may need settle retries; still not soft-accept."""
    import asyncio

    from flex_testing_agent.capabilities.crs_off import _probe_parameterized_get
    from flex_testing_agent.catalog import FLEX_HTTP_ENDPOINTS

    async def _instant_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    route = respx.get(
        "http://127.0.0.1:31950/runs/ended-1/commandsAsPreSerializedList"
    ).mock(
        side_effect=[
            httpx.Response(
                503,
                json={
                    "errors": [
                        {
                            "id": "PreSerializedCommandsNotAvailable",
                            "detail": "settling",
                        }
                    ]
                },
            ),
            httpx.Response(
                200, json={"data": [], "meta": {"cursor": 0, "totalLength": 0}}
            ),
        ]
    )
    spec = next(
        s
        for s in FLEX_HTTP_ENDPOINTS
        if s.name == "get_runs_runId_commandsAsPreSerializedList"
    )
    async with FlexRobot(settings) as robot:
        result = await _probe_parameterized_get(
            robot,
            spec,
            "/runs/ended-1/commandsAsPreSerializedList",
        )
    assert result.ok is True
    assert result.status_code == 200
    assert route.call_count == 2


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
    _mock_crs_off_auth()
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
    # Accept any remaining parameterized GETs
    respx.get(url__regex=r"http://127\.0\.0\.1:31950/.*").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )

    async with FlexRobot(settings) as robot:
        result = await run_crs_off_tier_b(robot, create_fixtures=False)

    assert result.fixtures["protocol_id"] == "p1"
    assert result.fixtures["run_id"] == "r1"
    assert result.fixtures["subsystem"] == "gantry_x"
    assert result.fixtures["client_data_key"] == CLIENT_DATA_KEY
    assert result.fixtures["log_identifier"] == "api.log"
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
    _mock_crs_off_auth()
    async with FlexRobot(settings) as robot:
        with pytest.raises(MutationDeniedError):
            await run_crs_off_tier_c(robot)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_tier_c_reversible_mutations(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    _mock_crs_off_auth()
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
    respx.put(f"http://127.0.0.1:31950/clientData/{CLIENT_DATA_KEY}").mock(
        return_value=httpx.Response(200, json=client_data_body)
    )
    respx.get(f"http://127.0.0.1:31950/clientData/{CLIENT_DATA_KEY}").mock(
        return_value=httpx.Response(200, json=client_data_body)
    )
    respx.delete(f"http://127.0.0.1:31950/clientData/{CLIENT_DATA_KEY}").mock(
        return_value=httpx.Response(200, json={"data": None})
    )

    respx.get("http://127.0.0.1:31950/camera").mock(
        return_value=httpx.Response(200, json={"cameraEnabled": True})
    )
    respx.post("http://127.0.0.1:31950/camera").mock(
        side_effect=[
            httpx.Response(200, json={"cameraEnabled": False}),
            httpx.Response(200, json={"cameraEnabled": True}),
        ]
    )
    stream_settings = {
        "source": "opentronsusb",
        "resolution": {"width": 1280, "height": 720},
        "framerate": 10,
        "bitrate": 300,
    }
    respx.get("http://127.0.0.1:31950/camera/stream/settings").mock(
        return_value=httpx.Response(200, json=stream_settings)
    )
    respx.post("http://127.0.0.1:31950/camera/stream/settings").mock(
        return_value=httpx.Response(200, json={"data": stream_settings})
    )

    respx.get("http://127.0.0.1:31950/errorRecovery/settings").mock(
        return_value=httpx.Response(200, json={"data": {"enabled": True}})
    )
    respx.patch("http://127.0.0.1:31950/errorRecovery/settings").mock(
        side_effect=[
            httpx.Response(200, json={"data": {"enabled": False}}),
            httpx.Response(200, json={"data": {"enabled": True}}),
        ]
    )

    respx.post("http://127.0.0.1:31950/labwareOffsets").mock(
        return_value=httpx.Response(201, json={"data": {"id": "off-1"}})
    )
    respx.post("http://127.0.0.1:31950/labwareOffsets/searches").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.delete("http://127.0.0.1:31950/labwareOffsets/off-1").mock(
        return_value=httpx.Response(200, json={"data": None})
    )

    respx.post("http://127.0.0.1:31950/protocols").mock(
        return_value=httpx.Response(201, json={"data": {"id": "p-tierc"}})
    )
    respx.get("http://127.0.0.1:31950/protocols/p-tierc/analyses").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "a1", "status": "completed"}]}
        )
    )
    respx.post("http://127.0.0.1:31950/runs").mock(
        return_value=httpx.Response(
            201, json={"data": {"id": "r-tierc", "current": True, "status": "idle"}}
        )
    )
    respx.patch("http://127.0.0.1:31950/runs/r-tierc").mock(
        return_value=httpx.Response(
            200, json={"data": {"id": "r-tierc", "current": False}}
        )
    )
    respx.delete("http://127.0.0.1:31950/runs/r-tierc").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    respx.delete("http://127.0.0.1:31950/protocols/p-tierc").mock(
        return_value=httpx.Response(200, json={"data": None})
    )

    async with FlexRobot(settings) as robot:
        result = await run_crs_off_tier_c(robot)

    assert result.fail_count == 0
    assert result.ok_count >= 7
    names = {step.name for step in result.steps}
    assert "lights_toggle_restore" in names
    assert "error_recovery_restore" in names
    assert "protocol_run_delete" in names
