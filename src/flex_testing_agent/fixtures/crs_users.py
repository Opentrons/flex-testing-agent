"""Load CRS-on test user fixtures from YAML."""

from __future__ import annotations

import os
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

AccountType = Literal["admin", "user", "auditor", "service"]

_DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parent / "crs_users.yaml"


class CrsUserFixture(BaseModel):
    """One provisionable CRS test account."""

    username: str
    full_name: str
    account_type: AccountType
    enabled: bool = True
    env_suffix: str = Field(
        description="Suffix for CRS_PASSWORD_{env_suffix} env override.",
    )
    notes: str | None = None


class CrsBootstrapAdmin(BaseModel):
    """Hardcoded bootstrap admin used by ``flex-test crs enable``."""

    username: str
    password: str
    full_name: str


class CrsUserFixtureFile(BaseModel):
    """Parsed crs_users.yaml."""

    version: int = 1
    bootstrap_admin: CrsBootstrapAdmin | None = None
    defaults: dict[str, str] = Field(default_factory=dict)
    users: list[CrsUserFixture] = Field(default_factory=list)

    def enabled_users(self) -> list[CrsUserFixture]:
        return [user for user in self.users if user.enabled]

    def require_bootstrap_admin(self) -> CrsBootstrapAdmin:
        if self.bootstrap_admin is None:
            raise ValueError("crs_users.yaml missing bootstrap_admin section")
        return self.bootstrap_admin


def resolve_fixture_password(
    fixture: CrsUserFixture,
    *,
    defaults: dict[str, str] | None = None,
) -> str | None:
    """Resolve password from env, then bundled lab default."""
    suffix = fixture.env_suffix.upper()
    specific = os.environ.get(f"CRS_PASSWORD_{suffix}", "").strip()
    if specific:
        return specific
    default_key = (defaults or {}).get("password_env", "CRS_FIXTURE_PASSWORD")
    shared = os.environ.get(default_key, "").strip()
    if shared:
        return shared
    lab_password = (defaults or {}).get("lab_password", "").strip()
    return lab_password or None


def resolve_user_password(
    username: str,
    *,
    fixture_file: CrsUserFixtureFile | None = None,
    settings: object | None = None,
) -> str | None:
    """Resolve password for a fixture or bootstrap admin username."""
    loaded = fixture_file or load_crs_user_fixtures()
    bootstrap = loaded.bootstrap_admin
    if bootstrap is not None and bootstrap.username == username:
        _, password = resolve_bootstrap_admin_credentials(loaded, settings)
        return password
    for user in loaded.users:
        if user.username == username:
            return resolve_fixture_password(user, defaults=loaded.defaults)
    return None


def resolve_bootstrap_admin_credentials(
    fixture_file: CrsUserFixtureFile,
    settings: object | None = None,
) -> tuple[str, str]:
    """Return bootstrap admin username/password (env overrides yaml defaults)."""
    bootstrap = fixture_file.require_bootstrap_admin()
    username = bootstrap.username
    password = bootstrap.password
    if settings is not None:
        settings_username = getattr(settings, "crs_admin_username", None)
        settings_password = getattr(settings, "crs_admin_password", None)
        if settings_username:
            username = settings_username.strip()
        if settings_password:
            password = settings_password.strip()
    env_username = os.environ.get("CRS_ADMIN_USERNAME", "").strip()
    env_password = os.environ.get("CRS_ADMIN_PASSWORD", "").strip()
    if env_username:
        username = env_username
    if env_password:
        password = env_password
    return username, password


def load_crs_user_fixtures(path: Path | None = None) -> CrsUserFixtureFile:
    """Load fixture YAML from *path* or the bundled default."""
    fixture_path = path or _DEFAULT_FIXTURE_PATH
    raw = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    if raw is None:
        return CrsUserFixtureFile()
    return CrsUserFixtureFile.model_validate(raw)


@lru_cache(maxsize=1)
def default_crs_user_fixtures() -> CrsUserFixtureFile:
    """Return cached bundled CRS user fixtures."""
    _ = resources.files("flex_testing_agent.fixtures")
    return load_crs_user_fixtures()
