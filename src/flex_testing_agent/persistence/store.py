"""Thin async persistence store over SQLAlchemy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from flex_testing_agent.models.run import RunStatus
from flex_testing_agent.models.snapshot import RobotSnapshot
from flex_testing_agent.persistence.models import (
    Base,
    CapabilityExecutionRecord,
    EvidenceArtifactRecord,
    RobotRecord,
    RunPhaseRecord,
    StateSnapshotRecord,
    TestRunRecord,
)


class SqlStore:
    """SQLite-backed store with a small domain-facing API."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        """Create tables (used in tests and first-run bootstrap)."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        """Dispose the engine."""
        await self._engine.dispose()

    async def upsert_robot(self, *, name: str, host: str) -> RobotRecord:
        """Insert or update a robot by host."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(RobotRecord).where(RobotRecord.host == host)
            )
            robot = result.scalar_one_or_none()
            if robot is None:
                robot = RobotRecord(
                    id=str(uuid4()),
                    name=name,
                    host=host,
                    created_at=datetime.now(UTC),
                )
                session.add(robot)
            else:
                robot.name = name
            await session.commit()
            await session.refresh(robot)
            return robot

    async def create_test_run(
        self,
        *,
        robot_id: str,
        run_id: str,
        command: str,
        evidence_directory: Path | None,
    ) -> TestRunRecord:
        """Create a pending/running test run."""
        async with self._session_factory() as session:
            record = TestRunRecord(
                id=run_id,
                robot_id=robot_id,
                status=RunStatus.RUNNING.value,
                command=command,
                evidence_directory=(
                    str(evidence_directory) if evidence_directory else None
                ),
                started_at=datetime.now(UTC),
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def finish_test_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        error_message: str | None = None,
    ) -> None:
        """Mark a test run finished."""
        async with self._session_factory() as session:
            record = await session.get(TestRunRecord, run_id)
            if record is None:
                return
            record.status = status.value
            record.error_message = error_message
            record.finished_at = datetime.now(UTC)
            await session.commit()

    async def add_phase(
        self,
        *,
        test_run_id: str,
        name: str,
        status: str,
        detail: str | None = None,
    ) -> RunPhaseRecord:
        """Append a run phase."""
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            phase = RunPhaseRecord(
                id=str(uuid4()),
                test_run_id=test_run_id,
                name=name,
                status=status,
                detail=detail,
                started_at=now,
                finished_at=now,
            )
            session.add(phase)
            await session.commit()
            await session.refresh(phase)
            return phase

    async def add_capability_execution(
        self,
        *,
        test_run_id: str,
        capability_name: str,
        risk_level: str,
        status: str,
        mutates_robot: bool,
        detail: str | None = None,
    ) -> CapabilityExecutionRecord:
        """Append a capability execution audit row."""
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = CapabilityExecutionRecord(
                id=str(uuid4()),
                test_run_id=test_run_id,
                capability_name=capability_name,
                risk_level=risk_level,
                status=status,
                mutates_robot=1 if mutates_robot else 0,
                detail=detail,
                started_at=now,
                finished_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def save_snapshot(
        self, *, test_run_id: str, snapshot: RobotSnapshot
    ) -> StateSnapshotRecord:
        """Persist a robot snapshot."""
        async with self._session_factory() as session:
            row = StateSnapshotRecord(
                id=str(uuid4()),
                test_run_id=test_run_id,
                captured_at=snapshot.captured_at,
                snapshot_json=snapshot.model_dump(mode="json"),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def add_evidence_artifact(
        self,
        *,
        test_run_id: str,
        name: str,
        path: Path,
    ) -> EvidenceArtifactRecord:
        """Record an evidence artifact path."""
        async with self._session_factory() as session:
            row = EvidenceArtifactRecord(
                id=str(uuid4()),
                test_run_id=test_run_id,
                name=name,
                path=str(path),
                content_type="application/json",
                created_at=datetime.now(UTC),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_test_run(self, run_id: str) -> TestRunRecord | None:
        """Fetch a test run by id."""
        async with self._session_factory() as session:
            return await session.get(TestRunRecord, run_id)

    async def session(self) -> AsyncSession:
        """Open a raw session (advanced use / tests)."""
        return self._session_factory()


def create_store(database_url: str) -> SqlStore:
    """Create a store for the given SQLAlchemy URL."""
    if database_url.startswith("sqlite") and ":///" in database_url:
        # Ensure parent directory exists for file-backed SQLite URLs.
        raw_path = database_url.split(":///", 1)[1]
        if raw_path and raw_path != ":memory:":
            Path(raw_path).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
    engine = create_async_engine(database_url, future=True)
    return SqlStore(engine)


async def bootstrap_store(database_url: str) -> SqlStore:
    """Create store and ensure schema exists (dev convenience)."""
    store = create_store(database_url)
    await store.create_schema()
    return store


__all__ = ["SqlStore", "bootstrap_store", "create_store"]
