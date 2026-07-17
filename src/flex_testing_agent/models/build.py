"""Build artifact models for robot OS installation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from flex_testing_agent.releases.urls import ReleaseChannel
from flex_testing_agent.releases.versions import ReleaseStability


class BuildArtifact(BaseModel):
    """A published Flex robot OS build resolved from releases.json."""

    version: str
    channel: ReleaseChannel
    stability: ReleaseStability
    stack_tag: str | None = None
    system_url: str
    full_image_url: str | None = None
    version_url: str | None = None
    release_notes_url: str | None = None
    manifest_bucket: str | None = None


class InstallResult(BaseModel):
    """Outcome of a robot OS install attempt."""

    requested_version: str
    channel: ReleaseChannel
    previous_system_version: str | None = None
    resulting_system_version: str | None = None
    session_token: str | None = None
    artifact_path: str | None = None
    auto_commit_and_restart: bool = True
    succeeded: bool = False
    detail: str = ""
    evidence_names: list[str] = Field(default_factory=list)
