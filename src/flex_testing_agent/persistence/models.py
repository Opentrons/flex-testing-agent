"""SQLAlchemy ORM models for harness records."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def _uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class RobotRecord(Base):
    """A physical or logical robot under test."""

    __tablename__ = "robots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    test_runs: Mapped[list[TestRunRecord]] = relationship(back_populates="robot")


class BuildRecord(Base):
    """Software build artifact reference (placeholder for install flows)."""

    __tablename__ = "builds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(255))
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TestRunRecord(Base):
    """Top-level harness execution record."""

    __tablename__ = "test_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    command: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_directory: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    robot: Mapped[RobotRecord] = relationship(back_populates="test_runs")
    phases: Mapped[list[RunPhaseRecord]] = relationship(back_populates="test_run")
    capability_executions: Mapped[list[CapabilityExecutionRecord]] = relationship(
        back_populates="test_run"
    )
    snapshots: Mapped[list[StateSnapshotRecord]] = relationship(
        back_populates="test_run"
    )


class RunPhaseRecord(Base):
    """Named phase within a test run."""

    __tablename__ = "run_phases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    test_run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    test_run: Mapped[TestRunRecord] = relationship(back_populates="phases")


class ScenarioExecutionRecord(Base):
    """Scenario execution audit row."""

    __tablename__ = "scenario_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    test_run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"), nullable=False)
    scenario_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CapabilityExecutionRecord(Base):
    """Capability execution audit row."""

    __tablename__ = "capability_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    test_run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"), nullable=False)
    capability_name: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    mutates_robot: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    test_run: Mapped[TestRunRecord] = relationship(
        back_populates="capability_executions"
    )


class StateSnapshotRecord(Base):
    """Persisted robot state snapshot."""

    __tablename__ = "state_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    test_run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    test_run: Mapped[TestRunRecord] = relationship(back_populates="snapshots")


class EvidenceArtifactRecord(Base):
    """Filesystem evidence artifact metadata."""

    __tablename__ = "evidence_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    test_run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), default="application/json")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ObservationRecord(Base):
    """Neutral observation captured during a run."""

    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    test_run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FindingRecord(Base):
    """Notable finding (issue, anomaly, or confirmation)."""

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    test_run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id"), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentSessionRecord(Base):
    """Placeholder for future agent session auditing."""

    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    test_run_id: Mapped[str | None] = mapped_column(ForeignKey("test_runs.id"))
    agent_runtime: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="unused")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class ToolInvocationRecord(Base):
    """Placeholder for future agent tool/action invocations."""

    __tablename__ = "tool_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_sessions.id")
    )
    test_run_id: Mapped[str | None] = mapped_column(ForeignKey("test_runs.id"))
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TokenUsageRecord(Base):
    """Placeholder for future agent token/cost usage."""

    __tablename__ = "token_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_sessions.id")
    )
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
