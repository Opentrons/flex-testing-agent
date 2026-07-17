"""Deterministic runner for installing a published Flex robot OS build."""

from __future__ import annotations

from flex_testing_agent.capabilities.install import INSTALL_DESCRIPTOR, install_build
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.evidence.store import EvidenceStore
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.build import InstallResult
from flex_testing_agent.models.run import RunStatus
from flex_testing_agent.orchestration.lock import RobotOperationLock
from flex_testing_agent.orchestration.run_context import RunContext
from flex_testing_agent.persistence.store import SqlStore, bootstrap_store
from flex_testing_agent.releases.urls import ReleaseChannel
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)


async def run_install(
    settings: Settings,
    version: str,
    *,
    channel: ReleaseChannel | None = None,
    store: SqlStore | None = None,
) -> tuple[RunContext, InstallResult]:
    """Install ``version`` on the configured robot and persist evidence."""
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
                command=f"install {version}",
                evidence_directory=evidence_dir,
            )
            await db.add_phase(
                test_run_id=ctx.run_id,
                name="start",
                status="succeeded",
                detail=f"install {version}",
            )

            async with FlexRobot(settings) as robot:
                result = await install_build(
                    robot,
                    version,
                    channel=channel,
                    download_directory=artifact_root / "downloads",
                )
                await db.add_capability_execution(
                    test_run_id=ctx.run_id,
                    capability_name=INSTALL_DESCRIPTOR.name,
                    risk_level=INSTALL_DESCRIPTOR.risk_level.value,
                    status="succeeded" if result.succeeded else "failed",
                    mutates_robot=True,
                    detail=result.detail,
                )
                for name, payload in robot.raw_evidence.items():
                    path_written = evidence.write_json(name, payload)
                    await db.add_evidence_artifact(
                        test_run_id=ctx.run_id,
                        name=name,
                        path=path_written,
                    )
                result_path = evidence.write_json(
                    "install_result", result.model_dump(mode="json")
                )
                await db.add_evidence_artifact(
                    test_run_id=ctx.run_id,
                    name="install_result",
                    path=result_path,
                )

            if result.succeeded:
                ctx.mark_succeeded()
                await db.finish_test_run(ctx.run_id, status=RunStatus.SUCCEEDED)
            else:
                ctx.mark_failed(result.detail)
                await db.finish_test_run(
                    ctx.run_id,
                    status=RunStatus.FAILED,
                    error_message=result.detail,
                )
            await db.add_phase(
                test_run_id=ctx.run_id,
                name="complete",
                status=ctx.status.value,
            )
            log.info(
                "install_complete",
                run_id=ctx.run_id,
                succeeded=result.succeeded,
                version=result.resulting_system_version,
            )
            return ctx, result
    except Exception as exc:
        ctx.mark_failed(str(exc))
        try:
            await db.finish_test_run(
                ctx.run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
        except Exception:
            log.exception("failed_to_persist_install_failure", run_id=ctx.run_id)
        raise
    finally:
        if owned_store:
            await db.dispose()
