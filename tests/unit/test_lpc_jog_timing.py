"""Unit tests for LPC jog safe-box planning and timing capability."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.lpc_jog_timing import run_lpc_jog_timing
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.lpc_jog_space import (
    DEFAULT_SAFE_BOX,
    MAX_JOG_COUNT,
    AxisBounds,
    SafeJogBox,
    latency_stats,
    percentile,
    plan_random_jogs,
)
from flex_testing_agent.orchestration.gates import MutationDeniedError
from flex_testing_agent.robots.flex import FlexRobot

_BASE = "http://127.0.0.1:31950"


@pytest.mark.unit
def test_plan_stays_in_box_and_never_drops_z() -> None:
    plan = plan_random_jogs(jog_count=80, rng_seed=42)
    assert plan.jog_count == 80
    box = DEFAULT_SAFE_BOX
    for jog in plan.jogs:
        assert box.contains(jog.x_after, jog.y_after, jog.z_after)
        assert jog.z_after >= -1e-9
        assert jog.axis in {"x", "y", "z"}
        assert abs(jog.distance_mm) in {0.1, 0.5, 1.0, 2.0}


@pytest.mark.unit
def test_plan_is_reproducible() -> None:
    a = plan_random_jogs(jog_count=40, rng_seed=7)
    b = plan_random_jogs(jog_count=40, rng_seed=7)
    assert [j.model_dump() for j in a.jogs] == [j.model_dump() for j in b.jogs]
    other = plan_random_jogs(jog_count=40, rng_seed=8)
    assert [j.model_dump() for j in a.jogs] != [j.model_dump() for j in other.jogs]


@pytest.mark.unit
def test_return_jogs_cancel_to_origin() -> None:
    plan = plan_random_jogs(jog_count=50, rng_seed=1)
    x = y = z = 0.0
    for jog in plan.jogs:
        if jog.axis == "x":
            x += jog.distance_mm
        elif jog.axis == "y":
            y += jog.distance_mm
        else:
            z += jog.distance_mm
    for jog in plan.return_jogs:
        if jog.axis == "x":
            x += jog.distance_mm
        elif jog.axis == "y":
            y += jog.distance_mm
        else:
            z += jog.distance_mm
    assert abs(x) < 1e-9
    assert abs(y) < 1e-9
    assert abs(z) < 1e-9
    assert plan.return_jogs[-1].x_after == 0.0
    assert plan.return_jogs[-1].y_after == 0.0
    assert plan.return_jogs[-1].z_after == 0.0


@pytest.mark.unit
def test_save_every_marks_confirm_jogs() -> None:
    plan = plan_random_jogs(jog_count=20, rng_seed=3, save_every=5)
    saved = [j.index for j in plan.jogs if j.save_position]
    assert saved == [4, 9, 14, 19]


@pytest.mark.unit
def test_rejects_negative_z_box() -> None:
    bad = SafeJogBox(
        x=DEFAULT_SAFE_BOX.x,
        y=DEFAULT_SAFE_BOX.y,
        z=AxisBounds(min_mm=-1.0, max_mm=10.0),
    )
    with pytest.raises(ValueError, match="z.min_mm"):
        plan_random_jogs(jog_count=4, box=bad)


@pytest.mark.unit
def test_many_seeds_never_drop_below_approach() -> None:
    for seed in range(25):
        plan = plan_random_jogs(jog_count=80, rng_seed=seed)
        for jog in plan.jogs:
            assert jog.z_after >= -1e-9


@pytest.mark.unit
def test_jog_count_bounds() -> None:
    with pytest.raises(ValueError, match="jog_count"):
        plan_random_jogs(jog_count=0)
    with pytest.raises(ValueError, match="jog_count"):
        plan_random_jogs(jog_count=MAX_JOG_COUNT + 1)


@pytest.mark.unit
def test_percentile_and_stats() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0.0) == 1.0
    assert percentile(values, 1.0) == 4.0
    assert percentile(values, 0.5) == 2.5
    stats = latency_stats("moveRelative", values)
    assert stats.count == 4
    assert stats.mean_seconds == 2.5
    assert stats.min_seconds == 1.0
    assert stats.max_seconds == 4.0


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path,
    )


def _mock_lpc_jog_http() -> None:
    respx.get(f"{_BASE}/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "test",
                "api_version": "7.0.0",
                "fw_version": "1",
                "system_version": "v10.0.0-alpha.1",
                "board_revision": "FLEX_B2",
                "robot_model": "OT-3 Standard",
                "robot_serial": "FLXTEST",
            },
        )
    )
    respx.get(f"{_BASE}/robot/door/status").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"status": "closed", "doorRequiredClosedForProtocol": True}},
        )
    )
    respx.get(f"{_BASE}/robot/control/estopStatus").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"status": "disengaged"}},
        )
    )
    respx.get(f"{_BASE}/instruments").mock(
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
    respx.get(f"{_BASE}/maintenance_runs/current_run").mock(
        return_value=httpx.Response(404, json={"errors": [{"detail": "none"}]})
    )
    respx.post(f"{_BASE}/maintenance_runs").mock(
        return_value=httpx.Response(201, json={"data": {"id": "mr-jog"}})
    )
    respx.post(url__regex=rf"{_BASE}/maintenance_runs/mr-jog/commands\?.*").mock(
        return_value=httpx.Response(
            201,
            json={"data": {"id": "c", "status": "succeeded", "commandType": "home"}},
        )
    )
    respx.delete(f"{_BASE}/maintenance_runs/mr-jog").mock(
        return_value=httpx.Response(200, json={"data": {"id": "mr-jog"}})
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_lpc_jog_timing_happy_path(tmp_path: Path) -> None:
    _mock_lpc_jog_http()
    async with FlexRobot(_settings(tmp_path)) as robot:
        result = await run_lpc_jog_timing(
            robot,
            confirm_clear_deck=True,
            jog_count=8,
            rng_seed=42,
            save_every=4,
        )
    assert result.ok is True
    assert result.maintenance_run_id == "mr-jog"
    assert result.jog_stats is not None
    assert result.jog_stats.count == 8
    assert result.save_stats is not None
    assert result.save_stats.count == 2
    assert result.timing_path is not None
    assert Path(result.timing_path).is_file()
    assert "loadPipette" in result.commands
    assert "moveToWell" in result.commands
    assert any(cmd.startswith("moveRelative:") for cmd in result.commands)
    assert any(cmd.startswith("savePosition:") for cmd in result.commands)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lpc_jog_timing_requires_confirm(tmp_path: Path) -> None:
    async with FlexRobot(_settings(tmp_path)) as robot:
        with pytest.raises(RuntimeError, match="confirm-clear-deck"):
            await run_lpc_jog_timing(robot, confirm_clear_deck=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lpc_jog_timing_rejects_low_approach(tmp_path: Path) -> None:
    async with FlexRobot(_settings(tmp_path)) as robot:
        with pytest.raises(ValueError, match="approach_z_mm"):
            await run_lpc_jog_timing(
                robot,
                confirm_clear_deck=True,
                approach_z_mm=10.0,
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_lpc_jog_timing_blocked_without_mutations(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        allow_mutations=False,
        artifact_directory=tmp_path,
    )
    async with FlexRobot(settings) as robot:
        with pytest.raises(MutationDeniedError):
            await run_lpc_jog_timing(robot, confirm_clear_deck=True)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_lpc_jog_timing_refuses_open_door(tmp_path: Path) -> None:
    _mock_lpc_jog_http()
    respx.get(f"{_BASE}/robot/door/status").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"status": "open"}},
        )
    )
    async with FlexRobot(_settings(tmp_path)) as robot:
        result = await run_lpc_jog_timing(
            robot,
            confirm_clear_deck=True,
            jog_count=4,
        )
    assert result.ok is False
    assert result.detail is not None
    assert "door" in result.detail.lower()
