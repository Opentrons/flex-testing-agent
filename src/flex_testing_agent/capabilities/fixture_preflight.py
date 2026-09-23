"""Inspect CRS fixture users and repair only when login is broken.

Retest scripts and live suites must not reprovision, replace, or rotate lab
passwords unless inspection shows the account is unusable (locked, missing, or
neither primary nor alternate ROPC credentials work).

Maps to harness policy in ``docs/crs-on-setup.md`` (fixture user hygiene).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from flex_testing_agent.capabilities.crs_auth import (
    access_token_for_username,
    recover_fixture_login_via_admin_reset,
)
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.crs_users import (
    load_crs_user_fixtures,
    resolve_user_password_pair,
)
from flex_testing_agent.models.auth_settings import AuthSettingsData
from flex_testing_agent.models.auth_users import TokenResponse, UpdateUserRequest
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session

LoginProbe = Literal["ok", "invalid_grant", "locked", "error", "skipped"]
WorkingCredential = Literal["primary", "alternate"]

_DEFAULT_PREFLIGHT_USERS = (
    "flex_test_admin",
    "flex_test_operator",
)


@dataclass(frozen=True, slots=True)
class AuthSettingsSnapshot:
    require_admin_creds_when_sending_protocol_to_robot: bool
    require_admin_creds_when_updating_robot_software: bool
    require_admin_creds_for_signoff_protocol: bool
    idle_logout: float

    @classmethod
    def from_settings(cls, data: AuthSettingsData) -> AuthSettingsSnapshot:
        return cls(
            require_admin_creds_when_sending_protocol_to_robot=(
                data.require_admin_creds_when_sending_protocol_to_robot
            ),
            require_admin_creds_when_updating_robot_software=(
                data.require_admin_creds_when_updating_robot_software
            ),
            require_admin_creds_for_signoff_protocol=(
                data.require_admin_creds_for_signoff_protocol
            ),
            idle_logout=data.idle_logout,
        )


@dataclass(frozen=True, slots=True)
class FixtureUserInspection:
    username: str
    exists: bool
    locked: bool | None
    reset_password: bool | None
    primary_probe: LoginProbe
    alternate_probe: LoginProbe
    working_credential: WorkingCredential | None
    repair_actions: tuple[str, ...]

    @property
    def login_ok(self) -> bool:
        return self.working_credential is not None

    @property
    def needs_repair(self) -> bool:
        if not self.exists:
            return True
        if self.locked:
            return True
        if self.reset_password:
            return True
        return not self.login_ok


@dataclass(frozen=True, slots=True)
class FixturePreflightResult:
    auth_settings: AuthSettingsSnapshot
    users: tuple[FixtureUserInspection, ...]
    repairs_performed: tuple[str, ...]
    ok: bool
    detail: str

    def inspection_for(self, username: str) -> FixtureUserInspection | None:
        for user in self.users:
            if user.username == username:
                return user
        return None

    def to_evidence(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "auth_settings": asdict(self.auth_settings),
            "users": [asdict(user) for user in self.users],
            "repairs_performed": list(self.repairs_performed),
        }


async def probe_fixture_ropc(
    settings: Settings,
    username: str,
    password: str,
) -> LoginProbe:
    """Try ROPC without password rotation, admin recovery, or finalize side effects."""
    async with build_robot_http_session(settings) as session:
        try:
            await OAuthClient(session).get_token(username, password)
        except RobotApiError as exc:
            body = (exc.body or "").lower()
            if exc.status_code in {400, 401} and "invalid_grant" in body:
                if "locked" in body:
                    return "locked"
                return "invalid_grant"
            return "error"
        else:
            return "ok"


async def _admin_token_for_preflight(settings: Settings) -> str:
    """Mint an admin token without triggering target-user password recovery."""
    fixtures = load_crs_user_fixtures()
    admin_usernames = [
        user.username
        for user in fixtures.enabled_users()
        if user.account_type == "admin" and not user.recovery_only
    ]
    bootstrap = fixtures.bootstrap_admin
    if bootstrap is not None and bootstrap.username not in admin_usernames:
        admin_usernames.insert(0, bootstrap.username)
    last_error: Exception | None = None
    for repair_reset in (False, True):
        for username in admin_usernames:
            try:
                return await access_token_for_username(
                    settings,
                    username,
                    allow_admin_recovery=False,
                    repair_reset_password=repair_reset,
                )
            except Exception as exc:
                last_error = exc
                continue
    if last_error is not None:
        raise last_error
    msg = "No admin fixture could authenticate for fixture preflight"
    raise RuntimeError(msg)


async def inspect_fixture_user(
    settings: Settings,
    admin: FlexRobot,
    *,
    username: str,
    admin_token: str,
) -> FixtureUserInspection:
    repair_actions: list[str] = []
    try:
        profile = await admin.users.get_user_by_username(
            username,
            access_token=admin_token,
        )
    except RobotApiError as exc:
        if exc.status_code == 404:
            return FixtureUserInspection(
                username=username,
                exists=False,
                locked=None,
                reset_password=None,
                primary_probe="skipped",
                alternate_probe="skipped",
                working_credential=None,
                repair_actions=tuple(repair_actions),
            )
        raise

    primary_probe: LoginProbe = "skipped"
    alternate_probe: LoginProbe = "skipped"
    working: WorkingCredential | None = None
    try:
        primary, alternate = resolve_user_password_pair(username, settings=settings)
    except ValueError:
        primary_probe = "error"
        alternate_probe = "skipped"
    else:
        primary_probe = await probe_fixture_ropc(settings, username, primary)
        if primary_probe == "ok":
            working = "primary"
        else:
            alternate_probe = await probe_fixture_ropc(settings, username, alternate)
            if alternate_probe == "ok":
                working = "alternate"

    return FixtureUserInspection(
        username=username,
        exists=True,
        locked=profile.locked,
        reset_password=profile.reset_password,
        primary_probe=primary_probe,
        alternate_probe=alternate_probe,
        working_credential=working,
        repair_actions=tuple(repair_actions),
    )


async def inspect_fixture_users(
    settings: Settings,
    *,
    usernames: tuple[str, ...] = _DEFAULT_PREFLIGHT_USERS,
) -> tuple[AuthSettingsSnapshot, tuple[FixtureUserInspection, ...]]:
    admin_token = await _admin_token_for_preflight(settings)
    async with FlexRobot(settings, access_token=admin_token) as admin:
        auth = AuthSettingsSnapshot.from_settings(
            await admin.auth_settings.get_settings(),
        )
        inspected: list[FixtureUserInspection] = []
        for username in usernames:
            inspected.append(
                await inspect_fixture_user(
                    settings,
                    admin,
                    username=username,
                    admin_token=admin_token,
                )
            )
    return auth, tuple(inspected)


async def _unlock_user(
    admin: FlexRobot,
    *,
    username: str,
    admin_token: str,
) -> str:
    await admin.users.update_user(
        username,
        UpdateUserRequest(locked=False),
        access_token=admin_token,
    )
    return f"unlocked {username}"


async def _repair_fixture_user(
    settings: Settings,
    admin: FlexRobot,
    *,
    username: str,
    admin_token: str,
    inspection: FixtureUserInspection,
) -> tuple[FixtureUserInspection, tuple[str, ...]]:
    repairs: list[str] = []
    if not inspection.exists:
        repairs.append(
            f"skipped {username}: user missing (run flex-test crs provision-users; "
            "preflight does not recreate users)",
        )
        return inspection, tuple(repairs)

    current = inspection
    if current.locked:
        repairs.append(
            await _unlock_user(admin, username=username, admin_token=admin_token)
        )
        current = await inspect_fixture_user(
            settings,
            admin,
            username=username,
            admin_token=admin_token,
        )

    if current.login_ok and not current.reset_password:
        return current, tuple(repairs)

    if current.login_ok and current.reset_password:
        token = await access_token_for_username(
            settings,
            username,
            allow_admin_recovery=False,
            repair_reset_password=True,
        )
        async with FlexRobot(settings, access_token=token) as user_robot:
            profile = await user_robot.users.get_self(access_token=token)
        if profile.reset_password:
            repairs.append(
                f"failed {username}: resetPassword still set after self rotation",
            )
        else:
            repairs.append(
                f"cleared resetPassword for {username} via self password rotation",
            )
        current = await inspect_fixture_user(
            settings,
            admin,
            username=username,
            admin_token=admin_token,
        )
        return current, tuple(repairs)

    primary, _alternate = resolve_user_password_pair(username, settings=settings)
    try:
        await recover_fixture_login_via_admin_reset(
            settings,
            target_username=username,
            admin_token=admin_token,
            lab_password=primary,
        )
    except (RobotApiError, RuntimeError, ValueError) as exc:
        repairs.append(f"failed {username}: admin password recovery failed ({exc})")
        return current, tuple(repairs)

    repairs.append(
        f"recovered {username}: admin resetPassword + restored lab primary password",
    )
    current = await inspect_fixture_user(
        settings,
        admin,
        username=username,
        admin_token=admin_token,
    )
    return current, tuple(repairs)


async def run_fixture_preflight(
    settings: Settings,
    *,
    usernames: tuple[str, ...] = _DEFAULT_PREFLIGHT_USERS,
    repair: bool = False,
) -> FixturePreflightResult:
    """Inspect fixture users; optionally repair only broken logins."""
    admin_token = await _admin_token_for_preflight(settings)
    repairs_performed: list[str] = []
    async with FlexRobot(settings, access_token=admin_token) as admin:
        auth = AuthSettingsSnapshot.from_settings(
            await admin.auth_settings.get_settings(),
        )
        inspected: list[FixtureUserInspection] = []
        for username in usernames:
            current = await inspect_fixture_user(
                settings,
                admin,
                username=username,
                admin_token=admin_token,
            )
            if repair and current.needs_repair:
                current, user_repairs = await _repair_fixture_user(
                    settings,
                    admin,
                    username=username,
                    admin_token=admin_token,
                    inspection=current,
                )
                repairs_performed.extend(user_repairs)
            inspected.append(current)

    broken = [user for user in inspected if not user.login_ok]
    if broken:
        names = ", ".join(user.username for user in broken)
        return FixturePreflightResult(
            auth_settings=auth,
            users=tuple(inspected),
            repairs_performed=tuple(repairs_performed),
            ok=False,
            detail=f"fixture login broken for: {names}",
        )
    pending_reset = [user.username for user in inspected if user.reset_password]
    if pending_reset:
        names = ", ".join(pending_reset)
        return FixturePreflightResult(
            auth_settings=auth,
            users=tuple(inspected),
            repairs_performed=tuple(repairs_performed),
            ok=False,
            detail=f"resetPassword still set for: {names}",
        )
    return FixturePreflightResult(
        auth_settings=auth,
        users=tuple(inspected),
        repairs_performed=tuple(repairs_performed),
        ok=True,
        detail="fixture users ready",
    )


async def ropc_token_for_fixture_user(
    settings: Settings,
    username: str,
    *,
    inspection: FixtureUserInspection | None = None,
) -> TokenResponse:
    """ROPC mint using inspected credentials without admin password recovery."""
    if inspection is not None and inspection.working_credential is not None:
        primary, alternate = resolve_user_password_pair(username, settings=settings)
        password = primary if inspection.working_credential == "primary" else alternate
        async with build_robot_http_session(settings) as session:
            return await OAuthClient(session).get_token(username, password)

    token = await access_token_for_username(
        settings,
        username,
        allow_admin_recovery=False,
        repair_reset_password=False,
    )
    return TokenResponse(
        access_token=token,
        token_type="Bearer",
        expires_in=0,
    )


async def access_token_for_fixture_user(
    settings: Settings,
    username: str,
    *,
    inspection: FixtureUserInspection | None = None,
) -> str:
    """Mint an access token using inspected credentials without admin recovery."""
    token = await ropc_token_for_fixture_user(
        settings,
        username,
        inspection=inspection,
    )
    return token.access_token
