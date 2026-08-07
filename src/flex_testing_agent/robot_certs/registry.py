"""YAML registry mapping Flex robots to trusted CA PEM files."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from flex_testing_agent.robot_certs.paths import (
    DEFAULT_HTTP_PORT,
    DEFAULT_HTTPS_PORT,
    ensure_robot_certs_dir,
    registry_path,
)


class RobotCertRegistryError(Exception):
    """Missing or invalid robot certificate registry."""


class RobotCertEntry(BaseModel):
    """One robot's trusted CA and connection metadata."""

    robot_serial: str
    ip: str
    ca_cert: str = Field(description="PEM filename relative to robot-certs dir")
    http_port: int = DEFAULT_HTTP_PORT
    https_port: int = DEFAULT_HTTPS_PORT
    robot_name: str | None = None
    updated_at: str | None = None


class RobotCertRegistry(BaseModel):
    robots: list[RobotCertEntry] = Field(default_factory=list)


def load_registry(certs_dir: Path) -> RobotCertRegistry:
    """Load ``registry.yaml``; empty registry if absent."""
    path = registry_path(certs_dir)
    if not path.is_file():
        return RobotCertRegistry()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return RobotCertRegistry()
    return RobotCertRegistry.model_validate(raw)


def save_registry(registry: RobotCertRegistry, certs_dir: Path) -> Path:
    """Write ``registry.yaml``."""
    ensure_robot_certs_dir(certs_dir)
    path = registry_path(certs_dir)
    path.write_text(
        yaml.safe_dump(
            registry.model_dump(mode="json", exclude_none=True),
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    return path


def ca_pem_path(entry: RobotCertEntry, certs_dir: Path) -> Path:
    return certs_dir / entry.ca_cert


def find_by_ip(registry: RobotCertRegistry, ip: str) -> RobotCertEntry | None:
    for entry in registry.robots:
        if entry.ip == ip:
            return entry
    return None


def upsert_robot(
    registry: RobotCertRegistry,
    entry: RobotCertEntry,
) -> RobotCertRegistry:
    """Return a new registry with *entry* replaced or appended."""
    updated = entry.model_copy(
        update={"updated_at": datetime.now(tz=UTC).isoformat()},
    )
    robots = [robot for robot in registry.robots if robot.ip != entry.ip]
    robots.append(updated)
    return RobotCertRegistry(robots=robots)
