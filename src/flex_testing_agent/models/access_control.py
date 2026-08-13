"""Access-control / operating-mode detection models.

Milestone 1 detects access control state via GET. Enabling access control via
``PATCH /auth/settings/accessControlEnabled`` is exposed only as
``flex-test crs enable --confirm-one-way`` because the API accepts only
``true``. Disable is root-shell ``opentrons_disable_crs`` or EXEC-2176 wipe,
not the public HTTP API.
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
