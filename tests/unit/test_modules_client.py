"""Unit tests for modules client helpers."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.clients.modules import ModulesClient
from flex_testing_agent.clients.session import RobotHttpSession


@pytest.fixture
async def session() -> RobotHttpSession:
    client = RobotHttpSession("http://127.0.0.1:31950", timeout_seconds=1.0)
    yield client
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_list_modules_normalizes_tempdeck(session: RobotHttpSession) -> None:
    respx.get("http://127.0.0.1:31950/modules").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "mod-1",
                        "serialNumber": "TDV21P20211130D06",
                        "moduleType": "temperatureModuleType",
                        "moduleModel": "temperatureModuleV2",
                        "firmwareVersion": "v2.1.1",
                        "data": {"status": "idle", "currentTemperature": 22.0},
                        "usbPort": {"port": 1, "portGroup": "left"},
                    },
                    {
                        "id": "mod-1-dup",
                        "serialNumber": "TDV21P20211130D06",
                        "moduleType": "temperatureModuleType",
                        "moduleModel": "temperatureModuleV2",
                        "data": {"status": "idle", "currentTemperature": 22.0},
                    },
                ]
            },
        )
    )
    inventory = await ModulesClient(session).list_modules()
    assert inventory.count == 2
    assert inventory.duplicate_serials() == ["TDV21P20211130D06"]
    assert inventory.temperature_modules()[0].current_temperature == 22.0
