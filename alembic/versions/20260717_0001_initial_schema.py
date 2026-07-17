"""Initial harness persistence schema.

Revision ID: 20260717_0001
Revises:
Create Date: 2026-07-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "robots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("host"),
    )
    op.create_table(
        "builds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("label", sa.String(length=255)),
        sa.Column("version", sa.String(length=255)),
        sa.Column("artifact_uri", sa.Text()),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "test_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("robot_id", sa.String(length=36), sa.ForeignKey("robots.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("command", sa.String(length=128), nullable=False),
        sa.Column("evidence_directory", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "run_phases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "test_run_id", sa.String(length=36), sa.ForeignKey("test_runs.id"), nullable=False
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "scenario_executions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "test_run_id", sa.String(length=36), sa.ForeignKey("test_runs.id"), nullable=False
        ),
        sa.Column("scenario_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("parameters_json", sa.JSON()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "capability_executions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "test_run_id", sa.String(length=36), sa.ForeignKey("test_runs.id"), nullable=False
        ),
        sa.Column("capability_name", sa.String(length=255), nullable=False),
        sa.Column("risk_level", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mutates_robot", sa.Integer(), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "state_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "test_run_id", sa.String(length=36), sa.ForeignKey("test_runs.id"), nullable=False
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "evidence_artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "test_run_id", sa.String(length=36), sa.ForeignKey("test_runs.id"), nullable=False
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "test_run_id", sa.String(length=36), sa.ForeignKey("test_runs.id"), nullable=False
        ),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "test_run_id", sa.String(length=36), sa.ForeignKey("test_runs.id"), nullable=False
        ),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("test_run_id", sa.String(length=36), sa.ForeignKey("test_runs.id")),
        sa.Column("agent_runtime", sa.String(length=128)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", sa.JSON()),
    )
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agent_session_id", sa.String(length=36), sa.ForeignKey("agent_sessions.id")
        ),
        sa.Column("test_run_id", sa.String(length=36), sa.ForeignKey("test_runs.id")),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("input_json", sa.JSON()),
        sa.Column("output_json", sa.JSON()),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "token_usage",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agent_session_id", sa.String(length=36), sa.ForeignKey("agent_sessions.id")
        ),
        sa.Column("model", sa.String(length=128)),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("estimated_cost_usd", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("token_usage")
    op.drop_table("tool_invocations")
    op.drop_table("agent_sessions")
    op.drop_table("findings")
    op.drop_table("observations")
    op.drop_table("evidence_artifacts")
    op.drop_table("state_snapshots")
    op.drop_table("capability_executions")
    op.drop_table("scenario_executions")
    op.drop_table("run_phases")
    op.drop_table("test_runs")
    op.drop_table("builds")
    op.drop_table("robots")
