"""Ephemeral users and paths for CRS auth-settings behavior suite."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from flex_testing_agent.models.auth_users import AccountType

LOGIN_ATTEMPTS_USERNAME = "flex_harness_login"
DEFAULT_LOGIN_ATTEMPTS_PASSWORD = "FlexHarnessLogin1!"


@dataclass(frozen=True, slots=True)
class LoginAttemptsUserSpec:
    """Throwaway user for maxNumberOfLoginAttempts tests."""

    username: str
    password: str
    full_name: str
    account_type: AccountType

    @staticmethod
    def default() -> LoginAttemptsUserSpec:
        return LoginAttemptsUserSpec(
            username=LOGIN_ATTEMPTS_USERNAME,
            password=resolve_login_attempts_password(),
            full_name="Flex Harness Login Attempts",
            account_type="user",
        )


def resolve_login_attempts_password(
    default: str = DEFAULT_LOGIN_ATTEMPTS_PASSWORD,
) -> str:
    override = os.environ.get("CRS_LOGIN_ATTEMPTS_PASSWORD", "").strip()
    return override or default


def default_smoke_protocol_path() -> Path:
    """No-motion smoke protocol used for protocol-upload gate tests."""
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "docs/test-suggestions/protocols/pyro_smoke_no_motion.py"
