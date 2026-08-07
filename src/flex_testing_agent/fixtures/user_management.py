"""Idempotent ephemeral users for auth-server CRUD coverage."""

from __future__ import annotations

import os
from dataclasses import dataclass

from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.clients.users import UsersClient
from flex_testing_agent.models.auth_users import AccountType, UserCreateRequest

EPHEMERAL_USERNAME = "flex_harness_um_crud"
EPHEMERAL_USERNAME_RENAMED = "flex_um_crud_renamed"
DEFAULT_EPHEMERAL_PASSWORD = "FlexHarnessUm1!"
DEFAULT_EPHEMERAL_PASSWORD_ROTATED = "FlexHarnessUm2!"


@dataclass(frozen=True, slots=True)
class EphemeralUserSpec:
    """Lab-safe throwaway account for user-management API tests."""

    username: str
    password: str
    full_name: str
    account_type: AccountType

    @staticmethod
    def default() -> EphemeralUserSpec:
        return EphemeralUserSpec(
            username=EPHEMERAL_USERNAME,
            password=resolve_ephemeral_password(DEFAULT_EPHEMERAL_PASSWORD),
            full_name="Flex Harness UM CRUD",
            account_type="user",
        )


def resolve_ephemeral_password(default: str = DEFAULT_EPHEMERAL_PASSWORD) -> str:
    """Resolve password from CRS_UM_TEST_PASSWORD or bundled default."""
    override = os.environ.get("CRS_UM_TEST_PASSWORD", "").strip()
    return override or default


async def ensure_user_absent(
    users: UsersClient,
    username: str,
    *,
    admin_token: str,
) -> bool:
    """Delete *username* when present. Returns True if a user was removed."""
    return await users.delete_user_if_exists(username, access_token=admin_token)


async def ensure_user_present(
    users: UsersClient,
    spec: EphemeralUserSpec,
    *,
    admin_token: str,
) -> UserCreateRequest:
    """Idempotent create: remove any prior copy, then POST a fresh user."""
    await ensure_user_absent(users, spec.username, admin_token=admin_token)
    await users.create_user(
        username=spec.username,
        password=spec.password,
        full_name=spec.full_name,
        account_type=spec.account_type,
        access_token=admin_token,
    )
    return UserCreateRequest(
        username=spec.username,
        password=spec.password,
        fullName=spec.full_name,
        accountType=spec.account_type,
    )


async def token_for_user(
    oauth: OAuthClient,
    username: str,
    password: str,
) -> str:
    """Return bearer access token for ROPC login."""
    response = await oauth.get_token(username, password)
    return response.access_token


async def verify_user_missing(
    users: UsersClient,
    username: str,
    *,
    admin_token: str,
) -> None:
    """Assert GET byUsername returns 404."""
    try:
        await users.get_user_by_username(username, access_token=admin_token)
    except RobotApiError as exc:
        if exc.status_code == 404:
            return
        raise
    raise AssertionError(f"expected 404 for deleted user {username!r}")
