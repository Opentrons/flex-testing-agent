"""Shared CRS-on OAuth helpers (avoids import cycles between probe and suites)."""

from __future__ import annotations

from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.crs_users import (
    fixture_password_for_reset,
    resolve_user_password,
    resolve_user_password_pair,
)
from flex_testing_agent.models.access_control import AccessControlState
from flex_testing_agent.models.auth_users import UpdateSelfRequest
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session

# Recovery admin order: backup first (recovery-only), then lab admins.
_ADMIN_RECOVERY_USERNAMES = (
    "flex_backup_admin",
    "flex_test_admin",
    "flex_harness_admin",
)


async def access_token_for_username(
    settings: Settings,
    username: str,
    *,
    allow_admin_recovery: bool = True,
    repair_reset_password: bool = True,
) -> str:
    """ROPC token for a fixture or bootstrap admin user.

    When ``resetPassword`` is set (App/admin reset) and ``repair_reset_password``
    is true, completes the product flow via ``PATCH /auth/users/self`` with a new
    password, or admin ``POST .../resetPassword`` + temp login + self rotation.
    Never touches the auth DB directly.

    Retest scripts should call ``run_fixture_preflight(..., repair=True)`` first,
    then mint with ``allow_admin_recovery=False`` and ``repair_reset_password=False``
    so lab passwords are not rotated unless preflight explicitly repairs a user.
    """
    candidates = _login_password_candidates(username, settings=settings)

    last_error: Exception | None = None
    for password in candidates:
        try:
            access_token = await _ropc_access_token(settings, username, password)
            return await _finalize_robot_login(
                settings,
                username=username,
                password=password,
                access_token=access_token,
                repair_reset_password=repair_reset_password,
            )
        except Exception as exc:
            last_error = exc
            continue

    if allow_admin_recovery:
        admin_token = await _first_available_admin_token(
            settings,
            exclude_username=username,
        )
        if admin_token is not None:
            primary, _alternate = _fixture_password_pair(username, settings=settings)
            return await recover_fixture_login_via_admin_reset(
                settings,
                target_username=username,
                admin_token=admin_token,
                lab_password=primary,
            )

    if last_error is not None:
        raise last_error
    msg = f"No password for user {username!r}; check crs_users.yaml or .env"
    raise ValueError(msg)


async def clear_pending_password_reset_via_api(
    settings: Settings,
    *,
    username: str,
    access_token: str,
    new_password: str,
) -> str:
    """Complete forced reset: self password change clears flag, then remint."""
    async with FlexRobot(settings, access_token=access_token) as robot:
        updated = await robot.users.update_self(
            UpdateSelfRequest(password=new_password),
            access_token=access_token,
        )
        if updated.reset_password:
            msg = (
                f"PATCH /auth/users/self left resetPassword=true for {username!r}; "
                "password change did not clear the flag"
            )
            raise RuntimeError(msg)
    return await _ropc_access_token(settings, username, new_password)


async def recover_fixture_login_via_admin_reset(
    settings: Settings,
    *,
    target_username: str,
    admin_token: str,
    lab_password: str,
) -> str:
    """Admin resetPassword, temp login, self password set to lab default (API only)."""
    async with FlexRobot(settings, access_token=admin_token) as admin:
        reset = await admin.users.reset_password(
            target_username,
            access_token=admin_token,
        )
    temp_token = await _ropc_access_token(
        settings,
        target_username,
        reset.temporary_password,
    )
    return await clear_pending_password_reset_via_api(
        settings,
        username=target_username,
        access_token=temp_token,
        new_password=lab_password,
    )


async def ensure_crs_on(robot: FlexRobot) -> None:
    """Fail fast when access control is not enabled."""
    status = await robot.auth_settings.detect_access_control()
    if status.state != AccessControlState.ENABLED:
        raise RuntimeError(
            "CRS / access control is not enabled; use flex-test probe for CRS-off. "
            f"state={status.state.value}"
        )


def _login_password_candidates(
    username: str,
    *,
    settings: Settings,
) -> tuple[str, ...]:
    try:
        primary, alternate = _fixture_password_pair(username, settings=settings)
    except ValueError:
        password = resolve_user_password(username, settings=settings)
        if not password:
            raise ValueError(
                f"No password for user {username!r}; check crs_users.yaml or .env"
            ) from None
        return (password,)
    return (primary, alternate)


def _fixture_password_pair(
    username: str,
    *,
    settings: Settings,
) -> tuple[str, str]:
    return resolve_user_password_pair(username, settings=settings)


async def _ropc_access_token(
    settings: Settings,
    username: str,
    password: str,
) -> str:
    async with build_robot_http_session(settings) as session:
        token = await OAuthClient(session).get_token(username, password)
    return token.access_token


async def _finalize_robot_login(
    settings: Settings,
    *,
    username: str,
    password: str,
    access_token: str,
    repair_reset_password: bool = True,
) -> str:
    """Clear pending ``resetPassword`` through self or admin reset API flows."""
    async with FlexRobot(settings, access_token=access_token) as robot:
        profile = await robot.users.get_self(access_token=access_token)
        if not profile.reset_password:
            return access_token

    if not repair_reset_password:
        msg = (
            f"{username!r} has resetPassword=true; run fixture preflight repair "
            "or complete password setup in the App before minting tokens"
        )
        raise RuntimeError(msg)

    primary, alternate = _fixture_password_pair(username, settings=settings)
    new_password = fixture_password_for_reset(
        password,
        primary_password=primary,
        alternate_password=alternate,
    )
    try:
        return await clear_pending_password_reset_via_api(
            settings,
            username=username,
            access_token=access_token,
            new_password=new_password,
        )
    except (RobotApiError, RuntimeError):
        pass

    admin_token = await _first_available_admin_token(
        settings,
        exclude_username=username,
    )
    if admin_token is None:
        msg = (
            f"Could not clear resetPassword for {username!r} via self PATCH and "
            "no recovery admin token was available"
        )
        raise RuntimeError(msg)
    return await recover_fixture_login_via_admin_reset(
        settings,
        target_username=username,
        admin_token=admin_token,
        lab_password=primary,
    )


async def _first_available_admin_token(
    settings: Settings,
    *,
    exclude_username: str,
) -> str | None:
    for admin_username in _ADMIN_RECOVERY_USERNAMES:
        if admin_username == exclude_username:
            continue
        try:
            return await access_token_for_username(
                settings,
                admin_username,
                allow_admin_recovery=False,
            )
        except Exception:
            continue
    return None
