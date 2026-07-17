"""Deterministic scenario runners (typed Python, YAML for metadata only)."""

from __future__ import annotations

from pathlib import Path

from flex_testing_agent.capabilities.inspect import inspect_robot
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.evidence.store import EvidenceStore
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.run import RunStatus
from flex_testing_agent.models.snapshot import RobotSnapshot
from flex_testing_agent.orchestration.lock import RobotOperationLock
from flex_testing_agent.orchestration.run_context import RunContext
from flex_testing_agent.persistence.store import SqlStore, bootstrap_store
from flex_testing_agent.robots.flex import FlexRobot
from flex_testing_agent.scenarios.loader import ScenarioMetadata, load_scenario_metadata

log = get_logger(__name__)


def _default_scenarios_dir() -> Path:
    """Resolve the repo-level scenarios directory when present."""
    candidates = [
        Path.cwd() / "scenarios",
        Path(__file__).resolve().parents[3] / "scenarios",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


async def run_inspect_scenario(
    settings: Settings,
    *,
    scenario_path: Path | None = None,
    store: SqlStore | None = None,
) -> tuple[RunContext, RobotSnapshot, ScenarioMetadata]:
    """Execute the inspect-robot scenario end-to-end.

    Steps:
        1. Load scenario metadata.
        2. Acquire robot lock.
        3. Persist test run.
        4. Inspect robot.
        5. Write evidence and snapshot.
        6. Finalize run status.
    """
    path = scenario_path or (_default_scenarios_dir() / "inspect-robot.yaml")
    metadata = load_scenario_metadata(path)

    owned_store = store is None
    db = store or await bootstrap_store(settings.database_url)
    artifact_root = settings.ensure_artifact_directory()
    ctx = RunContext(settings=settings)
    evidence_dir = artifact_root / "runs" / ctx.run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ctx.evidence_directory = evidence_dir
    evidence = EvidenceStore(evidence_dir)

    host = settings.require_robot_host()
    ctx.mark_running()

    try:
        with RobotOperationLock(host, artifact_root / "locks"):
            robot_row = await db.upsert_robot(name=settings.robot_name, host=host)
            await db.create_test_run(
                robot_id=robot_row.id,
                run_id=ctx.run_id,
                command="inspect",
                evidence_directory=evidence_dir,
            )
            await db.add_phase(
                test_run_id=ctx.run_id,
                name="start",
                status="succeeded",
                detail=f"scenario={metadata.name}",
            )

            async with FlexRobot(settings) as robot:
                snapshot = await inspect_robot(robot)
                await db.add_capability_execution(
                    test_run_id=ctx.run_id,
                    capability_name="inspect_robot",
                    risk_level="READ_ONLY",
                    status="succeeded" if snapshot.connectivity else "failed",
                    mutates_robot=False,
                    detail="; ".join(snapshot.errors) or None,
                )

                for name, payload in robot.raw_evidence.items():
                    path_written = evidence.write_json(name, payload)
                    await db.add_evidence_artifact(
                        test_run_id=ctx.run_id,
                        name=name,
                        path=path_written,
                    )

                snap_path = evidence.write_json(
                    "snapshot", snapshot.model_dump(mode="json")
                )
                await db.add_evidence_artifact(
                    test_run_id=ctx.run_id,
                    name="snapshot",
                    path=snap_path,
                )
                await db.save_snapshot(test_run_id=ctx.run_id, snapshot=snapshot)

            if not snapshot.connectivity:
                ctx.mark_failed("Robot was not reachable.")
                await db.finish_test_run(
                    ctx.run_id,
                    status=RunStatus.FAILED,
                    error_message=ctx.error_message,
                )
            else:
                ctx.mark_succeeded()
                await db.finish_test_run(ctx.run_id, status=RunStatus.SUCCEEDED)

            await db.add_phase(
                test_run_id=ctx.run_id,
                name="complete",
                status=ctx.status.value,
            )
            log.info(
                "inspect_complete",
                run_id=ctx.run_id,
                connectivity=snapshot.connectivity,
                access_control=snapshot.access_control.state.value,
            )
            return ctx, snapshot, metadata
    except Exception as exc:
        ctx.mark_failed(str(exc))
        try:
            await db.finish_test_run(
                ctx.run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
        except Exception:
            log.exception("failed_to_persist_run_failure", run_id=ctx.run_id)
        raise
    finally:
        if owned_store:
            await db.dispose()
