"""Unit tests for seed-runs helpers (no live robot)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.seed_runs import (
    SEED_SIGNOFF_LABEL,
    SeedId,
    SeedOutcome,
    parse_seed_ids,
    run_seed_runs,
    seed_signoff_label,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.robots.flex import FlexRobot


@pytest.mark.unit
def test_parse_seed_ids_all_when_empty() -> None:
    assert parse_seed_ids(None) is None
    assert parse_seed_ids([]) is None


@pytest.mark.unit
def test_parse_seed_ids_accepts_hyphen_or_underscore() -> None:
    assert parse_seed_ids(["simple_home_move", "cancel-mid-run"]) == [
        SeedId.SIMPLE_HOME_MOVE,
        SeedId.CANCEL_MID_RUN,
    ]


@pytest.mark.unit
def test_parse_seed_ids_new_pause_and_failed() -> None:
    assert parse_seed_ids(["pause_mid_run", "failed-intentional"]) == [
        SeedId.PAUSE_MID_RUN,
        SeedId.FAILED_INTENTIONAL,
    ]


@pytest.mark.unit
def test_parse_seed_ids_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown seed id"):
        parse_seed_ids(["not-a-seed"])


class _FakeSession:
    def __init__(self, token: str | None) -> None:
        self.access_token = token


class _FakeSettings:
    def __init__(self, notes: str | None) -> None:
        self.robot_user_notes = notes


class _FakeRobot:
    def __init__(self, token: str | None, notes: str | None) -> None:
        self.session = _FakeSession(token)
        self.settings = _FakeSettings(notes)


@pytest.mark.unit
def test_seed_signoff_label_none_without_oauth() -> None:
    assert seed_signoff_label(cast(FlexRobot, _FakeRobot(None, None))) is None


@pytest.mark.unit
def test_seed_signoff_label_default_with_oauth() -> None:
    assert (
        seed_signoff_label(cast(FlexRobot, _FakeRobot("token", None)))
        == SEED_SIGNOFF_LABEL
    )


@pytest.mark.unit
def test_seed_signoff_label_uses_configured_notes() -> None:
    assert (
        seed_signoff_label(cast(FlexRobot, _FakeRobot("token", "qa seed"))) == "qa seed"
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_seed_runs_applies_deck_before_each_seed(tmp_path: Path) -> None:
    """Each selected seed gets Kansas deck config before upload/play."""
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
                "system_version": "v10.0.0-alpha.4",
                "api_version": "10.0.0-alpha.4",
                "robot_model": "OT-3 Standard",
                "fw_version": "1",
                "board_revision": "1.0",
            },
        )
    )
    respx.get("http://127.0.0.1:31950/runs").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    deck_route = respx.put("http://127.0.0.1:31950/deck_configuration").mock(
        return_value=httpx.Response(200, json={"data": {"cutoutFixtures": []}})
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

    async def _fake_one_seed(
        robot: FlexRobot,
        spec: Any,
        timing: Any,
        *,
        picture_dir: Path,
    ) -> SeedOutcome:
        assert deck_route.call_count >= 1
        return SeedOutcome(seed_id=spec.seed_id.value, ok=True)

    async with FlexRobot(settings) as robot:
        with (
            patch(
                "flex_testing_agent.capabilities.seed_runs._preflight",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "flex_testing_agent.capabilities.seed_runs._run_one_seed",
                new=AsyncMock(side_effect=_fake_one_seed),
            ),
            patch(
                "flex_testing_agent.capabilities.seed_runs._run_lpc_seed",
                new=AsyncMock(),
            ),
        ):
            result = await run_seed_runs(
                robot,
                seed_ids=[SeedId.HEATER_SHAKER_BRIEF, SeedId.CANCEL_MID_RUN],
                update_firmware=False,
            )

    assert deck_route.call_count == 2
    assert result.ok_count == 2
    assert result.fail_count == 0
