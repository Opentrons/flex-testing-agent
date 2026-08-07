"""Unit tests for CRS-on combined suite."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.crs_off import TierBResult, TierCResult
from flex_testing_agent.capabilities.crs_on_probe import CrsOnTierAResult
from flex_testing_agent.capabilities.crs_on_suite import run_crs_on_suite
from flex_testing_agent.capabilities.probe import ProbeResult, RobotStateSummary
from flex_testing_agent.capabilities.user_management_suite import (
    UserManagementSuiteResult,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.orchestration.gates import MutationDeniedError


def _fake_tier_a() -> CrsOnTierAResult:
    return CrsOnTierAResult(
        probe=ProbeResult(
            summary=RobotStateSummary(probe_ok=51, probe_failed=0),
            probe={"results": []},
        ),
        user_management=UserManagementSuiteResult(
            ephemeral_username="flex_harness_um_crud",
            steps=[],
        ),
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_crs_on_suite_blocked_without_mutations(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    with pytest.raises(MutationDeniedError):
        await run_crs_on_suite(settings, include_auth_matrix=False)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_crs_on_suite_writes_summary_json(tmp_path: Path) -> None:
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
                "name": "test",
                "robot_model": "OT-3 Standard",
                "api_version": "4.0.0",
                "system_version": "ot3@4.0.0",
            },
        )
    )

    with (
        patch(
            "flex_testing_agent.capabilities.crs_on_suite.probe_crs_on",
            new_callable=AsyncMock,
            return_value=(_fake_tier_a(), None),
        ),
        patch(
            "flex_testing_agent.capabilities.crs_on_suite.run_crs_on_tier_b",
            new_callable=AsyncMock,
            return_value=TierBResult(ok_count=28, fail_count=0),
        ),
        patch(
            "flex_testing_agent.capabilities.crs_on_suite.run_crs_on_tier_c",
            new_callable=AsyncMock,
            return_value=TierCResult(ok_count=7, fail_count=0),
        ),
    ):
        result = await run_crs_on_suite(
            settings,
            include_auth_matrix=False,
            create_fixtures=False,
        )

    summary_path = tmp_path / "artifacts" / "crs_on_suite.json"
    assert summary_path.is_file()
    assert result.ok is True
    assert result.counts["tier_a_probe_ok"] == 51
    assert result.counts["tier_a_ok"] == 51
    assert result.counts["tier_b_ok"] == 28
    assert result.counts["tier_c_ok"] == 7
    assert result.timing_path is not None
