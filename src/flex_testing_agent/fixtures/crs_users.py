"""Load CRS-on test user fixtures from YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

AccountType = Literal["admin", "user", "auditor", "service"]

_DEFAULT_FIXTURE_PATH = Path(__file__).resolve().parent / "crs_users.yaml"


@dataclass(frozen=True)
class AdminLoginCandidate:
    """Desktop app admin login: username plus primary/alternate passwords."""

    username: str
    primary_password: str
    alternate_password: str


class CrsUserFixture(BaseModel):
    """One provisionable CRS test account."""

    username: str
    full_name: str
    account_type: AccountType
    enabled: bool = True
    env_suffix: str = Field(
        description="Suffix for CRS_PASSWORD_{env_suffix} env override.",
    )
    password: str | None = Field(
        default=None,
        description="Optional inline password (recovery accounts); env still wins.",
    )
    recovery_only: bool = Field(
        default=False,
        description="Provision but exclude from automated test login candidates.",
    )
    notes: str | None = None


class CrsBootstrapAdmin(BaseModel):
    """Hardcoded bootstrap admin used by ``flex-test crs enable``."""

    username: str
    password: str
    password_alt: str | None = Field(
        default=None,
        description="Alternate password for reset-password toggling in App/ODD flows.",
    )
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
    """Resolve primary password from env, then bundled lab default."""
    suffix = fixture.env_suffix.upper()
    specific = os.environ.get(f"CRS_PASSWORD_{suffix}", "").strip()
    if specific:
        return specific
    if fixture.password:
        return fixture.password.strip()
    default_key = (defaults or {}).get("password_env", "CRS_FIXTURE_PASSWORD")
    shared = os.environ.get(default_key, "").strip()
    if shared:
        return shared
    lab_password = (defaults or {}).get("lab_password", "").strip()
    return lab_password or None


def resolve_fixture_password_alt(
    fixture: CrsUserFixture | None,
    *,
    defaults: dict[str, str] | None = None,
) -> str:
    """Resolve alternate password for password-reset toggling."""
    loaded_defaults = defaults or {}
    if fixture is not None:
        suffix = fixture.env_suffix.upper()
        specific = os.environ.get(f"CRS_PASSWORD_{suffix}_ALT", "").strip()
        if specific:
            return specific
    alt_key = loaded_defaults.get("password_alt_env", "CRS_FIXTURE_PASSWORD_ALT")
    shared = os.environ.get(alt_key, "").strip()
    if shared:
        return shared
    lab_password_alt = loaded_defaults.get("lab_password_alt", "").strip()
    if not lab_password_alt:
        msg = "crs_users.yaml missing defaults.lab_password_alt"
        raise ValueError(msg)
    return lab_password_alt


def resolve_user_password_pair(
    username: str,
    *,
    fixture_file: CrsUserFixtureFile | None = None,
    settings: object | None = None,
) -> tuple[str, str]:
    """Return primary and alternate passwords for a fixture user."""
    loaded = fixture_file or load_crs_user_fixtures()
    bootstrap = loaded.bootstrap_admin
    if bootstrap is not None and bootstrap.username == username:
        _, password = resolve_bootstrap_admin_credentials(loaded, settings)
        alt = resolve_bootstrap_admin_password_alt(loaded, settings)
        if password == alt:
            msg = "bootstrap admin primary and alternate passwords must differ"
            raise ValueError(msg)
        return password, alt

    for user in loaded.users:
        if user.username == username:
            primary = resolve_fixture_password(user, defaults=loaded.defaults)
            if not primary:
                msg = f"No primary password resolved for {username}"
                raise ValueError(msg)
            alternate = resolve_fixture_password_alt(user, defaults=loaded.defaults)
            if primary == alternate:
                msg = f"Primary and alternate passwords must differ for {username}"
                raise ValueError(msg)
            return primary, alternate

    msg = f"Unknown fixture username: {username}"
    raise ValueError(msg)


def fixture_password_for_reset(
    current_password: str,
    *,
    primary_password: str,
    alternate_password: str,
) -> str:
    """Pick the lab alternate password after a forced reset."""
    if current_password == primary_password:
        return alternate_password
    if current_password == alternate_password:
        return primary_password
    return alternate_password


def admin_login_candidates(
    settings: object | None = None,
    *,
    fixture_file: CrsUserFixtureFile | None = None,
) -> list[AdminLoginCandidate]:
    """Return enabled admin accounts to try for desktop app login (in order)."""
    loaded = fixture_file or load_crs_user_fixtures()

    explicit_username = os.environ.get("CRS_APP_ADMIN_USERNAME", "").strip()
    if explicit_username:
        primary, alternate = _resolve_candidate_password_pair(
            explicit_username,
            loaded,
            settings,
        )
        return [
            AdminLoginCandidate(
                username=explicit_username,
                primary_password=primary,
                alternate_password=alternate,
            )
        ]

    ordered_usernames: list[str] = []
    for user in loaded.enabled_users():
        if user.account_type == "admin" and not user.recovery_only:
            ordered_usernames.append(user.username)

    bootstrap = loaded.bootstrap_admin
    if bootstrap is not None and bootstrap.username not in ordered_usernames:
        ordered_usernames.append(bootstrap.username)

    candidates: list[AdminLoginCandidate] = []
    for username in ordered_usernames:
        primary, alternate = _resolve_candidate_password_pair(
            username,
            loaded,
            settings,
        )
        candidates.append(
            AdminLoginCandidate(
                username=username,
                primary_password=primary,
                alternate_password=alternate,
            )
        )
    if not candidates:
        msg = "No enabled admin accounts found in crs_users.yaml"
        raise ValueError(msg)
    return candidates


def _resolve_candidate_password_pair(
    username: str,
    fixture_file: CrsUserFixtureFile,
    settings: object | None,
) -> tuple[str, str]:
    env_password = os.environ.get("CRS_APP_ADMIN_PASSWORD", "").strip()
    explicit_username = os.environ.get("CRS_APP_ADMIN_USERNAME", "").strip()
    if env_password and (not explicit_username or username == explicit_username):
        fixture = next(
            (user for user in fixture_file.users if user.username == username),
            None,
        )
        alternate = resolve_fixture_password_alt(
            fixture,
            defaults=fixture_file.defaults,
        )
        if env_password == alternate:
            msg = "CRS_APP_ADMIN_PASSWORD must differ from the alternate lab password"
            raise ValueError(msg)
        return env_password, alternate
    return resolve_user_password_pair(
        username,
        fixture_file=fixture_file,
        settings=settings,
    )


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


def resolve_bootstrap_admin_password_alt(
    fixture_file: CrsUserFixtureFile,
    settings: object | None = None,
) -> str:
    """Return bootstrap admin alternate password (env overrides yaml default)."""
    bootstrap = fixture_file.require_bootstrap_admin()
    password_alt = bootstrap.password_alt
    if settings is not None:
        settings_password_alt = getattr(settings, "crs_admin_password_alt", None)
        if settings_password_alt:
            password_alt = settings_password_alt.strip()
    env_password_alt = os.environ.get("CRS_ADMIN_PASSWORD_ALT", "").strip()
    if env_password_alt:
        password_alt = env_password_alt
    if password_alt:
        return password_alt
    return resolve_fixture_password_alt(None, defaults=fixture_file.defaults)


def expected_compliance_ui_usernames(
    fixture_file: CrsUserFixtureFile | None = None,
) -> list[str]:
    """Usernames that should appear in App Compliance Ready user management."""
    loaded = fixture_file or load_crs_user_fixtures()
    names = [user.username for user in loaded.enabled_users()]
    bootstrap = loaded.bootstrap_admin
    if bootstrap is not None and bootstrap.username not in names:
        names.append(bootstrap.username)
    return sorted(names)


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
