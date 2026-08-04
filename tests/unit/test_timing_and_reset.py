"""Unit tests for timing recorder and settings reset / known-state helpers."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.known_state import setup_known_state
from flex_testing_agent.capabilities.reset_data import reset_robot_data
from flex_testing_agent.clients.deck_configuration import kansas_deck_cutouts
from flex_testing_agent.clients.settings_reset import SettingsResetClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.orchestration.gates import MutationDeniedError
from flex_testing_agent.orchestration.timing import TimingSession, load_timing_reports
from flex_testing_agent.robots.flex import FlexRobot


@pytest.mark.unit
def test_timing_session_span_and_write(tmp_path: Path) -> None:
    session = TimingSession(label="unit", robot_host="127.0.0.1")
    with session.span("example"):
        pass
    path = session.write(tmp_path / "timing")
    assert path.is_file()
    reports = load_timing_reports(tmp_path / "timing")
    assert len(reports) == 1
    assert reports[0].spans[0].name == "example"
    assert reports[0].spans[0].duration_seconds is not None


@pytest.mark.unit
def test_kansas_deck_cutouts_fills_hs_serial() -> None:
    cutouts = kansas_deck_cutouts(heater_shaker_serial="HS123")
    hs = next(c for c in cutouts if c["cutoutId"] == "cutoutD1")
    assert hs["cutoutFixtureId"] == "heaterShakerModuleV1"
    assert hs["opentronsModuleSerialNumber"] == "HS123"
    assert any(c["cutoutFixtureId"] == "trashBinAdapter" for c in cutouts)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_settings_reset_client(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    respx.post("http://127.0.0.1:31950/settings/reset").mock(
        return_value=httpx.Response(200, json={"message": "ok"})
    )
    async with FlexRobot(settings) as robot:
        client = SettingsResetClient(robot.session)
        payload = await client.reset_selected({"runsHistory"})
    assert payload["message"] == "ok"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_reset_robot_data_requires_mutations(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    async with FlexRobot(settings) as robot:
        with pytest.raises(MutationDeniedError):
            await reset_robot_data(robot)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_known_state_setup_deck(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    respx.get("http://127.0.0.1:31950/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "KansasFLEX",
                "system_version": "v9.1.2-alpha.5",
                "api_version": "9.1.2-alpha.5",
                "robot_model": "OT-3 Standard",
                "fw_version": "1",
                "board_revision": "1.0",
            },
        )
    )
    respx.post("http://127.0.0.1:31950/settings/reset").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("http://127.0.0.1:31950/modules").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "m1",
                        "serialNumber": "HSDVT22041138",
                        "moduleType": "heaterShakerModuleType",
                        "moduleModel": "heaterShakerModuleV1",
                    }
                ]
            },
        )
    )
    respx.put("http://127.0.0.1:31950/deck_configuration").mock(
        return_value=httpx.Response(200, json={"data": {"cutoutFixtures": []}})
    )
    async with FlexRobot(settings) as robot:
        result = await setup_known_state(robot, reset_data=True, apply_deck=True)
    assert result.deck_applied is True
    assert result.reset_options == {"runsHistory": True}
    assert result.heater_shaker_serial == "HSDVT22041138"
