"""Mocked integration test for the inspect vertical slice."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.access_control import AccessControlState
from flex_testing_agent.models.run import RunStatus
from flex_testing_agent.persistence.store import bootstrap_store
from flex_testing_agent.scenarios.runner import run_inspect_scenario


@pytest.mark.integration
@pytest.mark.asyncio
@respx.mock
async def test_inspect_scenario_happy_path(
    settings: Settings,
    sample_health_payload: dict[str, object],
    sample_update_health_payload: dict[str, object],
) -> None:
    respx.get("http://127.0.0.1:31950/health").mock(
        return_value=httpx.Response(200, json=sample_health_payload)
    )
    respx.get("http://127.0.0.1:31950/server/update/health").mock(
        return_value=httpx.Response(200, json=sample_update_health_payload)
    )
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(200, json={"data": {"accessControlEnabled": False}})
    )

    store = await bootstrap_store(settings.database_url)
    scenario = Path(__file__).resolve().parents[2] / "scenarios" / "inspect-robot.yaml"
    try:
        ctx, snapshot, metadata = await run_inspect_scenario(
            settings,
            scenario_path=scenario,
            store=store,
        )
        assert metadata.name == "inspect-robot"
        assert snapshot.connectivity is True
        assert snapshot.access_control.state == AccessControlState.DISABLED
        assert ctx.status == RunStatus.SUCCEEDED
        assert ctx.evidence_directory is not None
        assert (ctx.evidence_directory / "snapshot.json").is_file()
        assert (ctx.evidence_directory / "health.json").is_file()
        run = await store.get_test_run(ctx.run_id)
        assert run is not None
        assert run.status == RunStatus.SUCCEEDED.value
    finally:
        await store.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
@respx.mock
async def test_inspect_reports_unknown_access_control_on_failure(
    settings: Settings,
    sample_health_payload: dict[str, object],
    sample_update_health_payload: dict[str, object],
) -> None:
    respx.get("http://127.0.0.1:31950/health").mock(
        return_value=httpx.Response(200, json=sample_health_payload)
    )
    respx.get("http://127.0.0.1:31950/server/update/health").mock(
        return_value=httpx.Response(200, json=sample_update_health_payload)
    )
    respx.get("http://127.0.0.1:31950/auth/settings/accessControlEnabled").mock(
        return_value=httpx.Response(503, text="down")
    )

    store = await bootstrap_store(settings.database_url)
    try:
        ctx, snapshot, _ = await run_inspect_scenario(settings, store=store)
        assert snapshot.connectivity is True
        assert snapshot.access_control.state == AccessControlState.UNKNOWN
        assert ctx.status == RunStatus.SUCCEEDED
    finally:
        await store.dispose()
