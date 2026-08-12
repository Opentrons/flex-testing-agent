"""Unit tests for wait-health and robot-status capabilities."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.robot_status import robot_status
from flex_testing_agent.capabilities.wait_health import wait_for_health
from flex_testing_agent.clients.instruments import InstrumentsClient
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.robots.flex import FlexRobot


def _settings() -> Settings:
    return Settings(
        robot_host="192.168.0.21",
        robot_name="KansasFLEX",
        allow_mutations=False,
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_instruments_client_lists_summaries() -> None:
    respx.get("http://192.168.0.21:31950/instruments").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "mount": "right",
                        "data": {"instrumentName": "p50_single_flex"},
                    }
                ]
            },
        )
    )
    async with RobotHttpSession("http://192.168.0.21:31950") as session:
        client = InstrumentsClient(session)
        items = await client.list_instrument_summaries()
    assert len(items) == 1
    assert items[0]["mount"] == "right"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_wait_for_health_succeeds_on_health_200() -> None:
    respx.get("http://192.168.0.21:31950/server/update/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "updateServerVersion": "10.0.0-alpha.0",
                "apiServerVersion": "10.0.0-alpha.0",
                "systemVersion": "v10.0.0-alpha.0",
            },
        )
    )
    respx.get("http://192.168.0.21:31950/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "KansasFLEX",
                "robot_model": "OT-3 Standard",
                "api_version": "10.0.0-alpha.0",
                "fw_version": "68",
                "board_revision": "FLEX_B2",
                "system_version": "v10.0.0-alpha.0",
                "robot_serial": "FLXA2020241021003",
            },
        )
    )
    async with FlexRobot(_settings()) as robot:
        result = await wait_for_health(
            robot, timeout_seconds=10.0, poll_interval_seconds=0.01
        )
    assert result.healthy is True
    assert result.system_version == "v10.0.0-alpha.0"
    assert result.polls >= 1


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_robot_status_uses_typed_clients() -> None:
    respx.get("http://192.168.0.21:31950/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "KansasFLEX",
                "robot_model": "OT-3 Standard",
                "api_version": "10.0.0-alpha.0",
                "fw_version": "68",
                "board_revision": "FLEX_B2",
                "system_version": "v10.0.0-alpha.0",
                "robot_serial": "FLXA2020241021003",
            },
        )
    )
    respx.get("http://192.168.0.21:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": True}})
    )
    respx.get("http://192.168.0.21:31950/robot/door/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "status": "closed",
                    "doorRequiredClosedForProtocol": True,
                }
            },
        )
    )
    respx.get("http://192.168.0.21:31950/instruments").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "mount": "right",
                        "data": {"instrumentName": "p50_single_flex"},
                    }
                ]
            },
        )
    )
    respx.get("http://192.168.0.21:31950/subsystems/status").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"name": "head", "ok": True}]},
        )
    )
    async with FlexRobot(_settings()) as robot:
        summary = await robot_status(robot)
    assert summary.system_version == "v10.0.0-alpha.0"
    assert summary.access_control_enabled is True
    assert summary.instruments[0]["mount"] == "right"
    assert summary.subsystems[0]["name"] == "head"
    assert not summary.errors
