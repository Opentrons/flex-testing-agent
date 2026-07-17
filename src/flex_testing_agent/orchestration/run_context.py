"""Shared context for a single harness test run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.run import RunStatus


@dataclass
class RunContext:
    """In-memory run metadata shared across orchestration steps."""

    settings: Settings
    run_id: str = field(default_factory=lambda: str(uuid4()))
    status: RunStatus = RunStatus.PENDING
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    evidence_directory: Path | None = None
    error_message: str | None = None

    def mark_running(self) -> None:
        """Transition run to running."""
        self.status = RunStatus.RUNNING

    def mark_succeeded(self) -> None:
        """Transition run to succeeded."""
        self.status = RunStatus.SUCCEEDED
        self.finished_at = datetime.now(UTC)

    def mark_failed(self, message: str) -> None:
        """Transition run to failed with a message."""
        self.status = RunStatus.FAILED
        self.error_message = message
        self.finished_at = datetime.now(UTC)
