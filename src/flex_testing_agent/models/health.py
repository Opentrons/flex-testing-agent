"""Normalized health models derived from robot-server and update-server."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DiskDetails(BaseModel):
    """Disk usage details from ``GET /health``.

    Some robot software versions omit fields such as ``systemTotalMb``; keep
    these optional so inspect/install still work.
    """

    model_config = ConfigDict(extra="ignore")

    system_available_mb: float | None = Field(default=None, alias="systemAvailableMb")
    system_total_mb: float | None = Field(default=None, alias="systemTotalMb")
    images_directory_size_mb: float | None = Field(
        default=None, alias="imagesDirectorySizeMb"
    )


class HealthReport(BaseModel):
    """Normalized robot-server health response.

    Source: ``robot-server/robot_server/health/models.py`` (``Health``).
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    robot_model: str
    api_version: str
    fw_version: str
    board_revision: str
    system_version: str
    robot_serial: str | None = None
    logs: list[str] = Field(default_factory=list)
    maximum_protocol_api_version: list[int] | None = None
    minimum_protocol_api_version: list[int] | None = None
    disk_details: DiskDetails | None = None
    links: dict[str, Any] | None = None

    @property
    def is_healthy(self) -> bool:
        """Return True when core identity fields are present."""
        return bool(self.name and self.api_version and self.system_version)


class UpdateHealthReport(BaseModel):
    """Normalized update-server health response.

    Source: ``update-server/otupdate/openembedded/__init__.py`` health handler.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    update_server_version: str = Field(alias="updateServerVersion")
    api_server_version: str = Field(alias="apiServerVersion")
    system_version: str = Field(alias="systemVersion")
    robot_model: str | None = Field(default=None, alias="robotModel")
    capabilities: dict[str, Any] = Field(default_factory=dict)
