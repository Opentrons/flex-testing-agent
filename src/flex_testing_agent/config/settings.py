"""Typed environment-driven settings for the harness."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    robot_host: str = Field(
        default="",
        description="Hostname or IP of the Flex robot under test.",
    )
    robot_name: str = Field(
        default="KansasFLEX",
        description="Informal name for the robot (for logs and records).",
    )
    opentrons_repo_path: Path | None = Field(
        default=None,
        description="Filesystem path to a local opentrons/opentrons clone.",
    )
    robot_stack_repo_path: Path | None = Field(
        default=None,
        description=(
            "Filesystem path to a local opentrons/robot-stack clone "
            "(release tagging and releases.json documentation)."
        ),
    )
    robot_http_port: int = Field(default=31950, ge=1, le=65535)
    robot_https_port: int = Field(default=32313, ge=1, le=65535)
    robot_use_https: bool = Field(
        default=False,
        description="Use HTTPS (requires CA trust). Milestone 1 defaults to HTTP.",
    )
    robot_request_timeout_seconds: float = Field(default=30.0, gt=0)
    robot_health_timeout_seconds: float = Field(default=10.0, gt=0)
    database_url: str = Field(
        default="sqlite+aiosqlite:///./artifacts/flex_testing.db",
    )
    artifact_directory: Path = Field(default=Path("./artifacts"))
    log_level: str = Field(default="INFO")
    allow_mutations: bool = Field(
        default=False,
        description="When false, mutating capabilities are rejected.",
    )
    dry_run: bool = Field(
        default=False,
        description="When true, mutating capabilities must not change robot state.",
    )
    robot_username: str | None = Field(
        default=None,
        description="Optional username for future access-control-on flows.",
    )
    robot_password: str | None = Field(
        default=None,
        description="Optional password for future access-control-on flows.",
    )

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def robot_base_url(self) -> str:
        """Return the configured robot API base URL."""
        scheme = "https" if self.robot_use_https else "http"
        port = self.robot_https_port if self.robot_use_https else self.robot_http_port
        return f"{scheme}://{self.robot_host}:{port}"

    def require_robot_host(self) -> str:
        """Return ROBOT_HOST or raise if unset."""
        if not self.robot_host.strip():
            raise ValueError(
                "ROBOT_HOST is required. Set it in the environment or .env file."
            )
        return self.robot_host.strip()

    def ensure_artifact_directory(self) -> Path:
        """Create and return the artifact directory."""
        path = self.artifact_directory.expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached settings instance."""
    return Settings()


def clear_settings_cache() -> None:
    """Clear the settings cache (for tests)."""
    get_settings.cache_clear()
