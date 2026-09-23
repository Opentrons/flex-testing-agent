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
        description="Preferred hostname or IP of the Flex robot under test.",
    )
    robot_host_candidates: str = Field(
        default="192.168.0.21,192.168.0.20",
        description=(
            "Comma-separated fallback hosts to probe when ROBOT_HOST is wrong "
            "or DHCP moved KansasFLEX. Tried after ROBOT_HOST."
        ),
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
        description=(
            "Use HTTPS :32313. CRS-off defaults to HTTP. When access control "
            "is on, discovery forces HTTPS even if this is false (requires "
            "`flex-test crs trust-ca`)."
        ),
    )
    robot_certs_dir: str = Field(
        default="",
        description=(
            "Directory for robot CA PEM files and registry.yaml. "
            "Empty means {ARTIFACT_DIRECTORY}/robot-certs."
        ),
    )
    robot_ca_pem: Path | None = Field(
        default=None,
        description="Optional explicit CA PEM path (overrides registry lookup).",
    )
    crs_service_password: str | None = Field(
        default=None,
        description=(
            "Robot Encryption Key for trust-ca CA decrypt (ODD rotating key). "
            "Not the CRS service PIN ({serial}-0000)."
        ),
    )
    crs_admin_username: str | None = Field(
        default=None,
        description="Bootstrap admin username for CRS-on user provisioning.",
    )
    crs_admin_password: str | None = Field(
        default=None,
        description="Bootstrap admin password for CRS-on user provisioning.",
    )
    crs_admin_password_alt: str | None = Field(
        default=None,
        description=("Bootstrap admin alternate password for reset-password toggling."),
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
    robot_user_notes: str | None = Field(
        default=None,
        description=(
            "Opentrons-User-Notes header for CRS-on mutating HTTP requests. "
            "When unset and OAuth is used, the harness supplies a default. "
            "Set to empty string to disable."
        ),
    )
    serial_port: str = Field(
        default="",
        description=(
            "FTDI serial console device path (e.g. /dev/cu.usbserial-…). "
            "Empty means auto-detect a likely Flex FTDI adapter."
        ),
    )
    serial_baud_rate: int = Field(
        default=115200,
        ge=300,
        le=4_000_000,
        description="Serial console baud rate (Flex FTDI default: 115200).",
    )
    robot_ssh_port: int = Field(
        default=22,
        ge=1,
        le=65535,
        description="Lab SSH port (CRS-off, or CRS-on with remote-access carveout).",
    )
    robot_ssh_user: str = Field(
        default="root",
        description="Lab SSH user (typical Flex images: root).",
    )
    robot_ssh_identity: Path | None = Field(
        default=None,
        description=(
            "Private key for lab SSH. Empty uses ~/.ssh/robot_key when that "
            "file exists. Not committed."
        ),
    )
    robot_ssh_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        description="SSH connect / BatchMode probe timeout.",
    )

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def robot_certs_directory(self) -> Path:
        """Directory for HTTPS CA PEM files and registry.yaml."""
        if self.robot_certs_dir.strip():
            return Path(self.robot_certs_dir).expanduser().resolve()
        return self.artifact_directory.expanduser().resolve() / "robot-certs"

    @property
    def robot_base_url(self) -> str:
        """Return the configured robot API base URL."""
        scheme = "https" if self.robot_use_https else "http"
        port = self.robot_https_port if self.robot_use_https else self.robot_http_port
        return f"{scheme}://{self.robot_host}:{port}"

    def candidate_hosts(self) -> list[str]:
        """Ordered unique hosts: ROBOT_HOST first, then ROBOT_HOST_CANDIDATES."""
        hosts: list[str] = []
        primary = self.robot_host.strip()
        if primary:
            hosts.append(primary)
        for part in self.robot_host_candidates.split(","):
            host = part.strip()
            if host and host not in hosts:
                hosts.append(host)
        return hosts

    def require_robot_host(self) -> str:
        """Return ROBOT_HOST, or the first candidate if ROBOT_HOST is empty.

        Prefer ``settings_with_resolved_host`` before live robot work so DHCP
        moves are handled by probing candidates.
        """
        candidates = self.candidate_hosts()
        if not candidates:
            raise ValueError(
                "ROBOT_HOST or ROBOT_HOST_CANDIDATES is required. "
                "Set them in the environment or .env file."
            )
        return candidates[0]

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
