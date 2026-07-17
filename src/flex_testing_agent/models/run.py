"""Test-run status enums."""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    """Lifecycle status for a persisted test run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
