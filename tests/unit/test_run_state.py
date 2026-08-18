"""Unit tests for protocol-run presence preflight."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.orchestration.gates import MutationDeniedError
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    RunStateError,
    ensure_run_state,
    parse_desired_run_state,
    snapshot_run_state,
)
from flex_testing_agent.robots.flex import FlexRobot


def _settings(tmp_path: Path, *, allow_mutations: bool) -> Settings:
    return Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=allow_mutations,
        artifact_directory=tmp_path / "artifacts",
    )


@pytest.mark.unit
def test_parse_desired_run_state() -> None:
    assert parse_desired_run_state("no-current") is DesiredRunState.NO_CURRENT
    assert parse_desired_run_state("CURRENT_IDLE") is DesiredRunState.CURRENT_IDLE
    with pytest.raises(ValueError):
        parse_desired_run_state("running")


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_snapshot_no_current(tmp_path: Path) -> None:
    respx.get("http://127.0.0.1:31950/runs").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"id": "r1", "current": False, "status": "stopped"}],
                "links": {},
            },
        )
    )
    async with FlexRobot(_settings(tmp_path, allow_mutations=False)) as robot:
        snap = await snapshot_run_state(robot)
    assert snap.matches(DesiredRunState.NO_CURRENT)
    assert not snap.matches(DesiredRunState.CURRENT_IDLE)
    assert snap.run_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_ensure_no_current_uncurrents(tmp_path: Path) -> None:
    runs_payload = {
        "data": [{"id": "r1", "current": True, "status": "idle"}],
        "links": {"current": {"href": "/runs/r1"}},
    }
    after_payload = {
        "data": [{"id": "r1", "current": False, "status": "stopped"}],
        "links": {},
    }
    respx.get("http://127.0.0.1:31950/runs").mock(
        side_effect=[
            httpx.Response(200, json=runs_payload),  # before
            httpx.Response(200, json=runs_payload),  # _uncurrent_all snapshot
            httpx.Response(200, json=runs_payload),  # _uncurrent_all list
            httpx.Response(200, json=after_payload),  # after verify
        ]
    )
    respx.get("http://127.0.0.1:31950/runs/r1").mock(
        return_value=httpx.Response(
            200, json={"data": {"id": "r1", "current": True, "status": "idle"}}
        )
    )
    respx.patch("http://127.0.0.1:31950/runs/r1").mock(
        return_value=httpx.Response(
            200, json={"data": {"id": "r1", "current": False, "status": "stopped"}}
        )
    )
    async with FlexRobot(_settings(tmp_path, allow_mutations=True)) as robot:
        snap = await ensure_run_state(robot, DesiredRunState.NO_CURRENT, ensure=True)
    assert snap.matches(DesiredRunState.NO_CURRENT)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_ensure_requires_mutations(tmp_path: Path) -> None:
    respx.get("http://127.0.0.1:31950/runs").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"id": "r1", "current": True, "status": "idle"}],
                "links": {"current": {"href": "/runs/r1"}},
            },
        )
    )
    async with FlexRobot(_settings(tmp_path, allow_mutations=False)) as robot:
        with pytest.raises(MutationDeniedError):
            await ensure_run_state(robot, DesiredRunState.NO_CURRENT, ensure=True)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_verify_mismatched_raises(tmp_path: Path) -> None:
    respx.get("http://127.0.0.1:31950/runs").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"id": "r1", "current": True, "status": "idle"}],
                "links": {"current": {"href": "/runs/r1"}},
            },
        )
    )
    async with FlexRobot(_settings(tmp_path, allow_mutations=False)) as robot:
        with pytest.raises(RunStateError, match="no-current"):
            await ensure_run_state(robot, DesiredRunState.NO_CURRENT, ensure=False)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_ensure_current_idle_creates(tmp_path: Path) -> None:
    empty = {"data": [], "links": {}}
    idle = {
        "data": [{"id": "r-new", "current": True, "status": "idle"}],
        "links": {"current": {"href": "/runs/r-new"}},
    }
    respx.get("http://127.0.0.1:31950/runs").mock(
        side_effect=[
            httpx.Response(200, json=empty),  # before
            httpx.Response(200, json=empty),  # _ensure_current_idle snapshot
            httpx.Response(200, json=idle),  # after verify
        ]
    )
    respx.get("http://127.0.0.1:31950/protocols").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "p1"}]})
    )
    respx.post("http://127.0.0.1:31950/runs").mock(
        return_value=httpx.Response(
            201, json={"data": {"id": "r-new", "current": True, "status": "idle"}}
        )
    )
    async with FlexRobot(_settings(tmp_path, allow_mutations=True)) as robot:
        snap = await ensure_run_state(
            robot,
            DesiredRunState.CURRENT_IDLE,
            ensure=True,
            protocol_id="p1",
        )
    assert snap.matches(DesiredRunState.CURRENT_IDLE)
    assert snap.current_run_id == "r-new"
