"""Aggregated robot snapshot for inspection results."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from flex_testing_agent.models.access_control import AccessControlStatus
from flex_testing_agent.models.health import HealthReport, UpdateHealthReport


class RobotSnapshot(BaseModel):
    """Point-in-time view of robot identity, versions, health, and mode."""

    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    configured_name: str
    host: str
    base_url: str
    connectivity: bool
    health: HealthReport | None = None
    update_health: UpdateHealthReport | None = None
    access_control: AccessControlStatus
    errors: list[str] = Field(default_factory=list)

    @property
    def installed_software_version(self) -> str | None:
        """Prefer robot-server system version, then update-server."""
        if self.health is not None:
            return self.health.system_version
        if self.update_health is not None:
            return self.update_health.system_version
        return None

    @property
    def api_version(self) -> str | None:
        """Return API version from health when available."""
        if self.health is not None:
            return self.health.api_version
        if self.update_health is not None:
            return self.update_health.api_server_version
        return None

    @property
    def robot_display_name(self) -> str:
        """Prefer live robot name from health over configured name."""
        if self.health is not None and self.health.name:
            return self.health.name
        return self.configured_name
