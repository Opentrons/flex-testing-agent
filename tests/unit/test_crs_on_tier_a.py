"""Unit tests for CRS-on Tier A composition."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from flex_testing_agent.capabilities.crs_on_probe import CrsOnTierAResult, probe_crs_on
from flex_testing_agent.capabilities.probe import ProbeResult, RobotStateSummary
from flex_testing_agent.capabilities.user_management_suite import (
    UserManagementSuiteResult,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.orchestration.gates import MutationDeniedError


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crs_on_tier_a_result_ok_when_both_pass() -> None:
    tier_a = CrsOnTierAResult(
        probe=ProbeResult(
            summary=RobotStateSummary(probe_ok=51, probe_failed=0),
            probe={"results": []},
        ),
        user_management=UserManagementSuiteResult(
            ephemeral_username="flex_harness_um_crud",
            steps=[],
        ),
    )
    assert tier_a.ok is True
    assert tier_a.failure_summary() == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_crs_on_runs_user_management_when_enabled(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    fake_probe = ProbeResult(
        summary=RobotStateSummary(probe_ok=51, probe_failed=0),
        probe={"results": []},
    )
    fake_users = UserManagementSuiteResult(
        ephemeral_username="flex_harness_um_crud",
        steps=[],
    )

    with (
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.probe_unauthenticated_baseline",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.access_token_for_username",
            new_callable=AsyncMock,
            return_value="tok",
        ),
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.FlexRobot",
        ) as robot_cls,
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.run_user_management_suite",
            new_callable=AsyncMock,
            return_value=fake_users,
        ) as run_users,
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.probe_robot",
            new_callable=AsyncMock,
            return_value=fake_probe,
        ),
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.ensure_crs_on",
            new_callable=AsyncMock,
        ),
    ):
        robot = robot_cls.return_value
        robot.__aenter__ = AsyncMock(return_value=robot)
        robot.__aexit__ = AsyncMock(return_value=None)
        robot.auth_settings.detect_access_control = AsyncMock()
        tier_a, baseline = await probe_crs_on(
            settings,
            username="flex_test_operator",
            include_unauth_baseline=False,
            include_user_management=True,
        )

    assert baseline is None
    assert tier_a.probe_ok == 51
    assert tier_a.user_management is fake_users
    run_users.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_crs_on_skips_user_management_when_disabled(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    fake_probe = ProbeResult(
        summary=RobotStateSummary(probe_ok=51, probe_failed=0),
        probe={"results": []},
    )

    with (
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.access_token_for_username",
            new_callable=AsyncMock,
            return_value="tok",
        ),
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.FlexRobot",
        ) as robot_cls,
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.run_user_management_suite",
            new_callable=AsyncMock,
        ) as run_users,
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.probe_robot",
            new_callable=AsyncMock,
            return_value=fake_probe,
        ),
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.ensure_crs_on",
            new_callable=AsyncMock,
        ),
    ):
        robot = robot_cls.return_value
        robot.__aenter__ = AsyncMock(return_value=robot)
        robot.__aexit__ = AsyncMock(return_value=None)
        tier_a, _ = await probe_crs_on(
            settings,
            username="flex_test_operator",
            include_unauth_baseline=False,
            include_user_management=False,
        )

    assert tier_a.user_management is None
    run_users.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_crs_on_user_management_requires_mutations(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    fake_probe = ProbeResult(
        summary=RobotStateSummary(probe_ok=51, probe_failed=0),
        probe={"results": []},
    )

    with (
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.access_token_for_username",
            new_callable=AsyncMock,
            return_value="tok",
        ),
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.FlexRobot",
        ) as robot_cls,
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.probe_robot",
            new_callable=AsyncMock,
            return_value=fake_probe,
        ),
        patch(
            "flex_testing_agent.capabilities.crs_on_probe.ensure_crs_on",
            new_callable=AsyncMock,
        ),
    ):
        robot = robot_cls.return_value
        robot.__aenter__ = AsyncMock(return_value=robot)
        robot.__aexit__ = AsyncMock(return_value=None)
        with pytest.raises(MutationDeniedError):
            await probe_crs_on(
                settings,
                username="flex_test_operator",
                include_unauth_baseline=False,
                include_user_management=True,
            )
