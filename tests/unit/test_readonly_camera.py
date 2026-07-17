"""Tests for readonly probe catalog and camera client."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.probe import summarize_probe
from flex_testing_agent.clients.camera import CameraClient
from flex_testing_agent.clients.readonly import (
    READONLY_ENDPOINTS,
    EndpointProbeResult,
    ReadonlyClient,
    ReadonlyProbeReport,
)
from flex_testing_agent.clients.session import RobotHttpSession


@pytest.fixture
async def session() -> RobotHttpSession:
    client = RobotHttpSession("http://127.0.0.1:31950", timeout_seconds=1.0)
    yield client
    await client.aclose()


@pytest.mark.unit
def test_readonly_catalog_covers_core_groups() -> None:
    groups = {endpoint.group for endpoint in READONLY_ENDPOINTS}
    assert {
        "system",
        "auth",
        "robot",
        "hardware",
        "protocols",
        "settings",
        "calibration",
        "network",
        "camera",
    }.issubset(groups)
    paths = {endpoint.path for endpoint in READONLY_ENDPOINTS}
    assert "/health" in paths
    assert "/camera" in paths
    assert "/instruments" in paths


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_readonly_probe_all(session: RobotHttpSession) -> None:
    for endpoint in READONLY_ENDPOINTS:
        respx.get(f"http://127.0.0.1:31950{endpoint.path}").mock(
            return_value=httpx.Response(200, json={"ok": True, "path": endpoint.path})
        )
    report = await ReadonlyClient(session).probe_all()
    assert report.ok_count == len(READONLY_ENDPOINTS)
    assert report.fail_count == 0
    assert report.payload("health") == {"ok": True, "path": "/health"}


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_camera_take_picture(session: RobotHttpSession, tmp_path: Path) -> None:
    jpeg = b"\xff\xd8\xfffakejpeg"
    respx.get("http://127.0.0.1:31950/camera").mock(
        return_value=httpx.Response(
            200,
            json={
                "cameraEnabled": True,
                "liveStreamEnabled": False,
                "errorRecoveryCameraEnabled": False,
            },
        )
    )
    respx.post("http://127.0.0.1:31950/camera/capturePreviewImage").mock(
        return_value=httpx.Response(
            200, content=jpeg, headers={"content-type": "image/jpeg"}
        )
    )
    camera = CameraClient(session)
    status = await camera.get_camera()
    assert status["cameraEnabled"] is True
    dest = tmp_path / "shot.jpg"
    saved = await camera.save_picture(dest)
    assert saved.read_bytes() == jpeg


@pytest.mark.unit
def test_summarize_probe() -> None:
    report = ReadonlyProbeReport(
        results=[
            EndpointProbeResult(
                name="health",
                path="/health",
                group="system",
                ok=True,
                status_code=200,
                payload={
                    "name": "KansasFLEX",
                    "robot_model": "OT-3 Standard",
                    "system_version": "9.1.2-alpha.0",
                    "api_version": "7.5.0",
                    "robot_serial": "FLXA1020250501001",
                },
            ),
            EndpointProbeResult(
                name="runs",
                path="/runs",
                group="protocols",
                ok=True,
                status_code=200,
                payload={"data": [{}, {}]},
            ),
            EndpointProbeResult(
                name="camera",
                path="/camera",
                group="camera",
                ok=False,
                status_code=503,
                error="HTTP 503",
            ),
        ]
    )
    summary = summarize_probe(report, host="192.168.0.20")
    assert summary.name == "KansasFLEX"
    assert summary.runs_count == 2
    assert summary.probe_ok == 2
    assert summary.probe_failed == 1
    assert summary.failed_endpoints == ["/camera (503)"]
