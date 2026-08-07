"""Paths for robot CA PEM files and registry.yaml."""

from __future__ import annotations

from pathlib import Path

DEFAULT_HTTP_PORT = 31950
DEFAULT_HTTPS_PORT = 32313

REGISTRY_FILENAME = "registry.yaml"


def default_robot_certs_dir(artifact_directory: Path) -> Path:
    """Return ``{artifact_directory}/robot-certs``."""
    return artifact_directory / "robot-certs"


def registry_path(certs_dir: Path) -> Path:
    return certs_dir / REGISTRY_FILENAME


def ensure_robot_certs_dir(certs_dir: Path) -> Path:
    certs_dir.mkdir(parents=True, exist_ok=True)
    return certs_dir
