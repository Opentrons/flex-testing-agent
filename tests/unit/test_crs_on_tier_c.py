"""Unit tests for CRS-on Tier C."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.crs_off import CLIENT_DATA_KEY
from flex_testing_agent.capabilities.crs_on_tier_c import run_crs_on_tier_c
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.orchestration.gates import MutationDeniedError


def _mock_crs_on_auth() -> None:
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": True}})
    )
    respx.post("http://127.0.0.1:31950/auth/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "test-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )


def _mock_tier_c_mutations() -> None:
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
    respx.get("http://127.0.0.1:31950/runs/r-tierc").mock(
        return_value=httpx.Response(
            200, json={"data": {"id": "r-tierc", "current": True, "status": "idle"}}
        )
    )
    respx.post("http://127.0.0.1:31950/runs/r-tierc/actions").mock(
        return_value=httpx.Response(
            201, json={"data": {"id": "act-stop", "actionType": "stop"}}
        )
    )
    respx.patch("http://127.0.0.1:31950/runs/r-tierc").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": {
                        "id": "r-tierc",
                        "signedBy": "flex_test_service flex-testing-agent",
                    }
                },
            ),
            httpx.Response(200, json={"data": {"id": "r-tierc", "current": False}}),
        ]
    )
    respx.delete("http://127.0.0.1:31950/runs/r-tierc").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    respx.delete("http://127.0.0.1:31950/protocols/p-tierc").mock(
        return_value=httpx.Response(200, json={"data": None})
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_crs_on_tier_c_blocked_without_mutations(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    with pytest.raises(MutationDeniedError):
        await run_crs_on_tier_c(settings, username="flex_test_service")


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_crs_on_tier_c_reversible_mutations(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    _mock_crs_on_auth()
    _mock_tier_c_mutations()

    result = await run_crs_on_tier_c(
        settings,
        username="flex_test_service",
        ensure_run_state_flag=False,
    )

    assert result.fail_count == 0
    assert result.ok_count >= 7
    names = {step.name for step in result.steps}
    assert "protocol_run_delete" in names
