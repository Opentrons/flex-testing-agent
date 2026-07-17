"""Persistence layer tests."""

from __future__ import annotations

import pytest

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.access_control import (
    AccessControlState,
    AccessControlStatus,
)
from flex_testing_agent.models.run import RunStatus
from flex_testing_agent.models.snapshot import RobotSnapshot
from flex_testing_agent.persistence.store import bootstrap_store


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_run_and_snapshot(settings: Settings) -> None:
    store = await bootstrap_store(settings.database_url)
    try:
        robot = await store.upsert_robot(name="Kansas", host="127.0.0.1")
        run = await store.create_test_run(
            robot_id=robot.id,
            run_id="run-1",
            command="inspect",
            evidence_directory=settings.artifact_directory / "runs" / "run-1",
        )
        snapshot = RobotSnapshot(
            configured_name="Kansas",
            host="127.0.0.1",
            base_url="http://127.0.0.1:31950",
            connectivity=True,
            access_control=AccessControlStatus(state=AccessControlState.DISABLED),
        )
        await store.save_snapshot(test_run_id=run.id, snapshot=snapshot)
        await store.finish_test_run(run.id, status=RunStatus.SUCCEEDED)
        loaded = await store.get_test_run(run.id)
        assert loaded is not None
        assert loaded.status == RunStatus.SUCCEEDED.value
    finally:
        await store.dispose()
