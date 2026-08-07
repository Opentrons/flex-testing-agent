"""Archive Flex diagnostic logs under ``ARTIFACT_DIRECTORY/logs/``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.logs import discover_log_identifiers
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

ARCHIVE_LOGS_DESCRIPTOR = CapabilityDescriptor(
    name="archive_diagnostic_logs",
    description=(
        "Download Flex diagnostic logs (GET /logs/{id}) into a dated archive "
        "under ARTIFACT_DIRECTORY/logs/. Read-only; soft-skips missing identifiers."
    ),
    risk_level=RiskLevel.READ_ONLY,
    mutates_robot=False,
    requires_cleanup=False,
    max_execution_time_seconds=180.0,
    required_robot_features=["health", "logs"],
    evidence_produced=["logs/", "manifest.json"],
    preconditions=["ROBOT_HOST configured", "robot reachable over HTTP(S)"],
    input_schema={
        "type": "object",
        "properties": {
            "identifiers": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional explicit log ids; default discovers from /health."
                ),
            },
            "destination": {
                "type": "string",
                "description": "Optional archive directory override.",
            },
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "archive_directory": {"type": "string"},
            "manifest_path": {"type": "string"},
            "downloaded": {"type": "integer"},
            "skipped": {"type": "integer"},
        },
    },
)


class ArchivedLogEntry(BaseModel):
    """One attempted log download in an archive."""

    identifier: str
    status_code: int | None = None
    path: str | None = None
    byte_size: int | None = None
    content_type: str | None = None
    skipped: bool = False
    detail: str | None = None


class ArchiveLogsResult(BaseModel):
    """Result of archiving diagnostic logs."""

    archive_directory: Path
    manifest_path: Path
    robot_host: str
    system_version: str | None = None
    api_version: str | None = None
    robot_name: str | None = None
    created_at: str
    entries: list[ArchivedLogEntry] = Field(default_factory=list)

    @property
    def downloaded(self) -> int:
        return sum(1 for e in self.entries if not e.skipped and e.path is not None)

    @property
    def skipped(self) -> int:
        return sum(1 for e in self.entries if e.skipped)


def _safe_host_slug(host: str) -> str:
    return host.replace(":", "-").replace("/", "-")


def _default_archive_dir(artifact_root: Path, host: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return artifact_root / "logs" / f"{stamp}-{_safe_host_slug(host)}"


async def archive_diagnostic_logs(
    robot: FlexRobot,
    *,
    identifiers: list[str] | None = None,
    destination: Path | None = None,
    log_timeout_seconds: float | None = None,
) -> ArchiveLogsResult:
    """Download diagnostic logs into a dated archive directory.

    Missing identifiers (HTTP 404) are recorded and skipped; other HTTP errors
    fail the capability.
    """
    ensure_mutation_allowed(
        robot.settings,
        risk_level=ARCHIVE_LOGS_DESCRIPTOR.risk_level,
        capability_name=ARCHIVE_LOGS_DESCRIPTOR.name,
    )
    host = robot.settings.require_robot_host()
    timeout = log_timeout_seconds
    if timeout is None:
        timeout = max(60.0, robot.settings.robot_request_timeout_seconds)

    health_raw: dict[str, Any] = {}
    system_version: str | None = None
    api_version: str | None = None
    robot_name: str | None = None
    try:
        health_raw = await robot.health.get_health_raw(
            timeout=robot.settings.robot_health_timeout_seconds
        )
        system_version = (
            str(health_raw["system_version"])
            if health_raw.get("system_version") is not None
            else None
        )
        api_version = (
            str(health_raw["api_version"])
            if health_raw.get("api_version") is not None
            else None
        )
        robot_name = (
            str(health_raw["name"]) if health_raw.get("name") is not None else None
        )
    except RobotApiError as exc:
        log.info("archive_logs_health_failed", error=str(exc))
        raise

    if identifiers is None:
        ids = discover_log_identifiers(health_raw, include_defaults=True)
    else:
        ids = [i.strip() for i in identifiers if i.strip()]

    archive_dir = destination or _default_archive_dir(
        robot.settings.ensure_artifact_directory(), host
    )
    archive_dir.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now(UTC).isoformat()
    entries: list[ArchivedLogEntry] = []

    for ident in ids:
        status, content, content_type = await robot.logs.try_get_log(
            ident, timeout=timeout
        )
        if status == 404 or content is None:
            entries.append(
                ArchivedLogEntry(
                    identifier=ident,
                    status_code=status,
                    skipped=True,
                    detail="not found",
                )
            )
            log.info("archive_log_skipped", identifier=ident, status_code=status)
            continue
        if status != 200:
            raise RobotApiError(
                f"HTTP {status} for /logs/{ident}",
                status_code=status,
                path=f"/logs/{ident}",
            )
        out_path = archive_dir / ident
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(content)
        entries.append(
            ArchivedLogEntry(
                identifier=ident,
                status_code=200,
                path=str(out_path),
                byte_size=len(content),
                content_type=content_type,
                skipped=False,
            )
        )
        log.info(
            "archive_log_saved",
            identifier=ident,
            path=str(out_path),
            byte_size=len(content),
        )

    result = ArchiveLogsResult(
        archive_directory=archive_dir,
        manifest_path=archive_dir / "manifest.json",
        robot_host=host,
        system_version=system_version,
        api_version=api_version,
        robot_name=robot_name,
        created_at=created_at,
        entries=entries,
    )

    manifest: dict[str, Any] = {
        "created_at": created_at,
        "robot_host": host,
        "robot_name": robot_name,
        "system_version": system_version,
        "api_version": api_version,
        "archive_directory": str(archive_dir),
        "downloaded": result.downloaded,
        "skipped": result.skipped,
        "health": {
            "system_version": system_version,
            "api_version": api_version,
            "name": robot_name,
            "logs": health_raw.get("logs"),
            "links": health_raw.get("links"),
        },
        "entries": [e.model_dump(mode="json") for e in entries],
    }
    result.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    robot.raw_evidence["archive_logs"] = manifest
    robot.raw_evidence["archive_logs_path"] = str(archive_dir)
    return result
