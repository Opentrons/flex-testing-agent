"""Access-control / operating-mode detection models.

Milestone 1 detects access control state only. Enabling access control via
``PATCH /auth/settings/accessControlEnabled`` is intentionally unsupported
because the robot API accepts only ``true`` and cannot disable it without
Opentrons assistance or an SSH data wipe.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AccessControlState(StrEnum):
    """Normalized access-control detection result."""

    DISABLED = "disabled"
    ENABLED = "enabled"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class AccessControlStatus(BaseModel):
    """Detected access-control state plus optional diagnostic detail."""

    state: AccessControlState
    raw_enabled: bool | None = Field(
        default=None,
        description="Raw boolean from the robot when the GET succeeded.",
    )
    detail: str | None = Field(
        default=None,
        description="Human-readable note when state is unknown or unsupported.",
    )
