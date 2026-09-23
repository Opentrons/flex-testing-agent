"""CRS-on user-management API coverage (all auth-server user verbs)."""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.clients.users import UsersClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.user_management import (
    DEFAULT_AUDITOR_ROTATED_PASSWORD,
    DEFAULT_EPHEMERAL_PASSWORD_ROTATED,
    EPHEMERAL_USERNAME_RENAMED,
    EPHEMERAL_USERNAME_SELF_TMP,
    EPHEMERAL_USERNAME_TOKEN_REV,
    EPHEMERAL_USERNAME_TOKEN_REV_REN,
    EphemeralUserSpec,
    ensure_user_absent,
    ensure_user_present,
    resolve_ephemeral_password,
    token_for_user,
    verify_user_missing,
)
from flex_testing_agent.models.auth_users import (
    AccountType,
    TokenResponse,
    UpdateSelfRequest,
    UpdateUserRequest,
)
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.robots.flex import FlexRobot

_DENY_STATUSES = (401, 403)
_REJECT_STATUSES = (400, 401, 409, 422)
_TOKEN_REVOKED_STATUSES = (401, 403)
_TOKEN_REVOKED_AFTER_DELETE_STATUSES = (401, 403, 404)

USER_MANAGEMENT_SUITE = CapabilityDescriptor(
    name="crs_on_user_management",
    description=(
        "CRS-on auth-server user CRUD suite: POST/GET/PATCH/DELETE users, "
        "account-type change, duplicate-username reject, non-admin 403, "
        "self fullName update, self routes after username rename (RQA-5950), "
        "admin edits that must revoke the subject's pre-issued token (RQA-5952), "
        "resetPassword (original + temp one-use), self password rotation, and "
        "OAuth introspect. Idempotent setup creates a throwaway "
        "flex_harness_um_crud account."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    mutates_robot=True,
    requires_cleanup=True,
    evidence_produced=["crs_on_user_management.json"],
    preconditions=[
        "ALLOW_MUTATIONS=true",
        "CRS / accessControlEnabled is true",
        "ROBOT_USE_HTTPS=true and CA trust configured",
        "Bootstrap admin OAuth (flex_harness_admin)",
        "Operator fixture (flex_test_operator) for non-admin 403 checks",
    ],
)


class UserManagementStepResult(BaseModel):
    """One REST verb exercised against auth-server user routes."""

    name: str
    method: str
    path: str
    ok: bool
    detail: str = ""


class UserManagementSuiteResult(BaseModel):
    """Aggregate result for the user-management API suite."""

    ephemeral_username: str
    steps: list[UserManagementStepResult] = Field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for step in self.steps if step.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for step in self.steps if not step.ok)


async def run_user_management_suite(
    settings: Settings,
    *,
    admin_username: str = "flex_harness_admin",
    operator_username: str = "flex_test_operator",
) -> UserManagementSuiteResult:
    """Run idempotent user-management API coverage on a CRS-enabled robot."""
    ensure_mutation_allowed(
        settings,
        risk_level=USER_MANAGEMENT_SUITE.risk_level,
        capability_name=USER_MANAGEMENT_SUITE.name,
    )
    spec = EphemeralUserSpec.default()
    admin_token = await access_token_for_username(settings, admin_username)
    operator_token = await access_token_for_username(settings, operator_username)

    async with FlexRobot(settings, access_token=admin_token) as robot:
        users = UsersClient(robot.session)
        oauth = OAuthClient(robot.session)
        steps: list[UserManagementStepResult] = []
        current_username = spec.username
        current_password = spec.password

        async def record(
            name: str,
            method: str,
            path: str,
            coro: Awaitable[str],
        ) -> None:
            try:
                detail = await coro
                steps.append(
                    UserManagementStepResult(
                        name=name,
                        method=method,
                        path=path,
                        ok=True,
                        detail=detail,
                    )
                )
            except Exception as exc:
                steps.append(
                    UserManagementStepResult(
                        name=name,
                        method=method,
                        path=path,
                        ok=False,
                        detail=str(exc),
                    )
                )

        await record(
            "setup_delete_if_exists",
            "DELETE",
            f"/auth/users/byUsername/{spec.username}",
            _setup_delete(users, spec.username, admin_token=admin_token),
        )
        await record(
            "setup_delete_self_tmp_if_exists",
            "DELETE",
            f"/auth/users/byUsername/{EPHEMERAL_USERNAME_SELF_TMP}",
            _setup_delete(users, EPHEMERAL_USERNAME_SELF_TMP, admin_token=admin_token),
        )
        await record(
            "setup_delete_token_rev_if_exists",
            "DELETE",
            f"/auth/users/byUsername/{EPHEMERAL_USERNAME_TOKEN_REV}",
            _setup_delete(users, EPHEMERAL_USERNAME_TOKEN_REV, admin_token=admin_token),
        )
        await record(
            "setup_delete_token_rev_renamed_if_exists",
            "DELETE",
            f"/auth/users/byUsername/{EPHEMERAL_USERNAME_TOKEN_REV_REN}",
            _setup_delete(
                users, EPHEMERAL_USERNAME_TOKEN_REV_REN, admin_token=admin_token
            ),
        )
        await record(
            "setup_delete_renamed_if_exists",
            "DELETE",
            f"/auth/users/byUsername/{EPHEMERAL_USERNAME_RENAMED}",
            _setup_delete(users, EPHEMERAL_USERNAME_RENAMED, admin_token=admin_token),
        )
        await record(
            "post_create_user",
            "POST",
            "/auth/users",
            _create(users, spec, admin_token=admin_token),
        )
        await record(
            "get_by_username",
            "GET",
            f"/auth/users/byUsername/{spec.username}",
            _get_by_username(users, spec.username, admin_token=admin_token),
        )

        subject_token = await token_for_user(oauth, spec.username, spec.password)
        await record(
            "get_self",
            "GET",
            "/auth/users/self",
            _get_self(users, access_token=subject_token),
        )
        await record(
            "patch_self_full_name",
            "PATCH",
            "/auth/users/self",
            _patch_self_full_name(
                users,
                access_token=subject_token,
                full_name="Flex Harness UM CRUD Self Renamed",
            ),
        )
        await record(
            "self_routes_after_username_change",
            "GET+PATCH",
            "/auth/users/self",
            _self_routes_after_username_change(
                users,
                oauth,
                access_token=subject_token,
                password=spec.password,
                original_username=spec.username,
                temp_username=EPHEMERAL_USERNAME_SELF_TMP,
                full_name="Flex Harness UM After Rename",
                restore_full_name=spec.full_name,
            ),
        )
        await record(
            "token_revoked_after_admin_edit_username",
            "GET",
            "/auth/users/self",
            _token_revoked_after_admin_edit_username(
                users, oauth, admin_token=admin_token, password=spec.password
            ),
        )
        await record(
            "token_revoked_after_admin_edit_role",
            "GET",
            "/auth/users/self",
            _token_revoked_after_admin_edit_role(
                users, oauth, admin_token=admin_token, password=spec.password
            ),
        )
        await record(
            "token_valid_after_admin_edit_legal_name",
            "GET",
            "/auth/users/self",
            _token_valid_after_admin_edit_legal_name(
                users, oauth, admin_token=admin_token, password=spec.password
            ),
        )
        await record(
            "token_revoked_after_admin_delete_user",
            "GET",
            "/auth/users/self",
            _token_revoked_after_admin_delete_user(
                users, oauth, admin_token=admin_token, password=spec.password
            ),
        )
        await record(
            "token_revoked_after_admin_lock_account",
            "GET",
            "/auth/users/self",
            _token_revoked_after_admin_lock_account(
                users, oauth, admin_token=admin_token, password=spec.password
            ),
        )
        await record(
            "token_revoked_after_admin_reset_password",
            "GET",
            "/auth/users/self",
            _token_revoked_after_admin_reset_password(
                users, oauth, admin_token=admin_token, password=spec.password
            ),
        )
        await record(
            "post_duplicate_username_rejected",
            "POST",
            "/auth/users",
            _duplicate_username_rejected(users, spec, admin_token=admin_token),
        )
        await record(
            "patch_account_type",
            "PATCH",
            f"/auth/users/byUsername/{spec.username}",
            _patch_account_type_roundtrip(
                users, spec.username, admin_token=admin_token
            ),
        )
        await record(
            "operator_patch_forbidden",
            "PATCH",
            f"/auth/users/byUsername/{spec.username}",
            _operator_patch_forbidden(
                users, spec.username, operator_token=operator_token
            ),
        )
        await record(
            "operator_delete_forbidden",
            "DELETE",
            f"/auth/users/byUsername/{spec.username}",
            _operator_delete_forbidden(
                users, spec.username, operator_token=operator_token
            ),
        )
        await record(
            "patch_by_username_profile",
            "PATCH",
            f"/auth/users/byUsername/{spec.username}",
            _patch_profile(users, spec.username, admin_token=admin_token),
        )
        await record(
            "patch_by_username_rename",
            "PATCH",
            f"/auth/users/byUsername/{spec.username}",
            _patch_rename(users, spec.username, admin_token=admin_token),
        )
        if steps[-1].ok:
            current_username = EPHEMERAL_USERNAME_RENAMED

        await record(
            "patch_by_username_reset_flag",
            "PATCH",
            f"/auth/users/byUsername/{current_username}",
            _patch_reset_flag(users, current_username, admin_token=admin_token),
        )

        temp_password: str | None = None

        async def _reset_and_capture() -> str:
            nonlocal temp_password, current_password
            reset = await users.reset_password(
                current_username,
                access_token=admin_token,
            )
            temp_password = reset.temporary_password
            current_password = temp_password
            return f"temporaryPassword=<redacted> resetPassword={reset.reset_password}"

        await record(
            "post_reset_password",
            "POST",
            f"/auth/users/byUsername/{current_username}/resetPassword",
            _reset_and_capture(),
        )

        if temp_password is not None:
            await record(
                "original_password_rejected_after_reset",
                "POST",
                "/auth/oauth2/token",
                _password_rejected(oauth, current_username, spec.password),
            )
            subject_token = await token_for_user(
                oauth,
                current_username,
                temp_password,
            )
            rotated = resolve_ephemeral_password(DEFAULT_EPHEMERAL_PASSWORD_ROTATED)
            await record(
                "patch_self_password",
                "PATCH",
                "/auth/users/self",
                _patch_self_password(
                    users,
                    access_token=subject_token,
                    new_password=rotated,
                ),
            )
            if steps[-1].ok:
                current_password = rotated
                await record(
                    "temp_password_rejected_after_rotation",
                    "POST",
                    "/auth/oauth2/token",
                    _password_rejected(oauth, current_username, temp_password),
                )
                subject_token = await token_for_user(
                    oauth,
                    current_username,
                    current_password,
                )
            await record(
                "get_self_after_password_change",
                "GET",
                "/auth/users/self",
                _get_self(users, access_token=subject_token),
            )
            await record(
                "post_oauth2_introspect",
                "POST",
                "/auth/oauth2/introspect",
                _introspect(oauth, subject_token),
            )

        await record(
            "delete_user",
            "DELETE",
            f"/auth/users/byUsername/{current_username}",
            _delete(users, current_username, admin_token=admin_token),
        )
        await record(
            "verify_deleted",
            "GET",
            f"/auth/users/byUsername/{current_username}",
            _verify_missing(users, current_username, admin_token=admin_token),
        )

        result = UserManagementSuiteResult(
            ephemeral_username=current_username,
            steps=steps,
        )
        robot.raw_evidence["crs_on_user_management"] = result.model_dump(mode="json")
        return result


async def _setup_delete(
    users: UsersClient,
    username: str,
    *,
    admin_token: str,
) -> str:
    removed = await ensure_user_absent(users, username, admin_token=admin_token)
    return "removed prior user" if removed else "already absent"


async def _create(
    users: UsersClient,
    spec: EphemeralUserSpec,
    *,
    admin_token: str,
) -> str:
    await ensure_user_present(users, spec, admin_token=admin_token)
    return f"username={spec.username} accountType={spec.account_type}"


async def _duplicate_username_rejected(
    users: UsersClient,
    spec: EphemeralUserSpec,
    *,
    admin_token: str,
) -> str:
    try:
        await users.create_user(
            username=spec.username,
            password=spec.password,
            full_name="Duplicate should fail",
            account_type=spec.account_type,
            access_token=admin_token,
        )
    except RobotApiError as exc:
        if exc.status_code in _REJECT_STATUSES:
            return f"rejected status={exc.status_code}"
        raise
    raise AssertionError(f"expected duplicate username {spec.username!r} to fail")


async def _patch_account_type_roundtrip(
    users: UsersClient,
    username: str,
    *,
    admin_token: str,
) -> str:
    auditor = await users.update_user(
        username,
        UpdateUserRequest(accountType="auditor"),
        access_token=admin_token,
    )
    if auditor.account_type != "auditor":
        raise AssertionError(f"expected auditor, got {auditor.account_type}")
    restored = await users.update_user(
        username,
        UpdateUserRequest(accountType="user"),
        access_token=admin_token,
    )
    if restored.account_type != "user":
        raise AssertionError(f"expected user, got {restored.account_type}")
    return "auditor then user"


async def _operator_patch_forbidden(
    users: UsersClient,
    username: str,
    *,
    operator_token: str,
) -> str:
    try:
        await users.update_user(
            username,
            UpdateUserRequest(fullName="Operator should not write"),
            access_token=operator_token,
        )
    except RobotApiError as exc:
        if exc.status_code in _DENY_STATUSES:
            return f"denied status={exc.status_code}"
        raise
    raise AssertionError("expected operator PATCH users to be denied")


async def _operator_delete_forbidden(
    users: UsersClient,
    username: str,
    *,
    operator_token: str,
) -> str:
    try:
        await users.delete_user(username, access_token=operator_token)
    except RobotApiError as exc:
        if exc.status_code in _DENY_STATUSES:
            return f"denied status={exc.status_code}"
        raise
    raise AssertionError("expected operator DELETE users to be denied")


async def _password_rejected(
    oauth: OAuthClient,
    username: str,
    password: str,
) -> str:
    try:
        await oauth.get_token(username, password)
    except RobotApiError as exc:
        if exc.status_code in _REJECT_STATUSES:
            return f"rejected status={exc.status_code}"
        raise
    raise AssertionError(f"expected ROPC to fail for {username!r}")


async def _get_by_username(
    users: UsersClient,
    username: str,
    *,
    admin_token: str,
) -> str:
    profile = await users.get_user_by_username(username, access_token=admin_token)
    return f"fullName={profile.full_name} accountType={profile.account_type}"


async def _get_self(users: UsersClient, *, access_token: str) -> str:
    profile = await users.get_self(access_token=access_token)
    return f"username={profile.user_name} resetPassword={profile.reset_password}"


async def _patch_profile(
    users: UsersClient,
    username: str,
    *,
    admin_token: str,
) -> str:
    updated = await users.update_user(
        username,
        UpdateUserRequest(fullName="Flex Harness UM CRUD Updated"),
        access_token=admin_token,
    )
    return f"fullName={updated.full_name}"


async def _patch_rename(
    users: UsersClient,
    username: str,
    *,
    admin_token: str,
) -> str:
    updated = await users.update_user(
        username,
        UpdateUserRequest(username=EPHEMERAL_USERNAME_RENAMED),
        access_token=admin_token,
    )
    return f"username={updated.user_name}"


async def _patch_reset_flag(
    users: UsersClient,
    username: str,
    *,
    admin_token: str,
) -> str:
    updated = await users.update_user(
        username,
        UpdateUserRequest(resetPassword=True),
        access_token=admin_token,
    )
    return f"resetPassword={updated.reset_password}"


async def _patch_self_full_name(
    users: UsersClient,
    *,
    access_token: str,
    full_name: str,
) -> str:
    updated = await users.update_self(
        UpdateSelfRequest(fullName=full_name),
        access_token=access_token,
    )
    if updated.full_name != full_name:
        raise AssertionError(
            f"expected fullName={full_name!r}, got {updated.full_name!r}"
        )
    return f"fullName={updated.full_name}"


async def _self_routes_after_username_change(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    access_token: str,
    password: str,
    original_username: str,
    temp_username: str,
    full_name: str,
    restore_full_name: str,
) -> str:
    """After self username change, the same session must still hit /auth/users/self.

    RQA-5950: pre-rename tokens currently 500 on GET and PATCH /auth/users/self.
    Always restores ``original_username`` so later suite steps keep working.
    """
    await users.update_self(
        UpdateSelfRequest(username=temp_username),
        access_token=access_token,
    )
    failures: list[str] = []
    try:
        try:
            await users.get_self(access_token=access_token)
        except RobotApiError as exc:
            failures.append(f"GET /auth/users/self HTTP {exc.status_code}")
        try:
            updated = await users.update_self(
                UpdateSelfRequest(fullName=full_name),
                access_token=access_token,
            )
            if updated.full_name != full_name:
                failures.append(
                    f"PATCH fullName expected {full_name!r}, got {updated.full_name!r}"
                )
        except RobotApiError as exc:
            failures.append(f"PATCH /auth/users/self fullName HTTP {exc.status_code}")
    finally:
        reminted = await token_for_user(oauth, temp_username, password)
        restored = await users.update_self(
            UpdateSelfRequest(
                username=original_username,
                fullName=restore_full_name,
            ),
            access_token=reminted,
        )
        if restored.user_name != original_username:
            raise AssertionError(
                f"failed to restore username={original_username!r}, "
                f"got {restored.user_name!r}"
            )
    if failures:
        raise AssertionError(
            "RQA-5950: pre-rename token must still use /auth/users/self after "
            "username change; " + "; ".join(failures)
        )
    return (
        f"same-token GET+PATCH /auth/users/self after rename ok "
        f"(restored {original_username})"
    )


async def _mint_token_revocation_subject(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    spec = EphemeralUserSpec(
        username=EPHEMERAL_USERNAME_TOKEN_REV,
        password=password,
        full_name="Flex Harness UM Token Rev",
        account_type="user",
    )
    await ensure_user_present(users, spec, admin_token=admin_token)
    return await token_for_user(oauth, spec.username, spec.password)


async def _cleanup_token_revocation_users(
    users: UsersClient,
    *,
    admin_token: str,
) -> None:
    await ensure_user_absent(
        users, EPHEMERAL_USERNAME_TOKEN_REV, admin_token=admin_token
    )
    await ensure_user_absent(
        users, EPHEMERAL_USERNAME_TOKEN_REV_REN, admin_token=admin_token
    )


async def _self_status(users: UsersClient, access_token: str) -> int:
    try:
        await users.get_self(access_token=access_token)
    except RobotApiError as exc:
        return exc.status_code if exc.status_code is not None else 0
    return 200


async def _patch_self_status(
    users: UsersClient,
    access_token: str,
    *,
    full_name: str,
) -> int:
    try:
        await users.update_self(
            UpdateSelfRequest(fullName=full_name),
            access_token=access_token,
        )
    except RobotApiError as exc:
        return exc.status_code if exc.status_code is not None else 0
    return 200


def _assert_token_revoked(
    status: int, *, action: str, accepted: tuple[int, ...], route: str
) -> None:
    if status in accepted:
        return
    accepted_text = "/".join(str(code) for code in accepted)
    raise AssertionError(
        f"RQA-5952: after admin {action}, expected {route} "
        f"{accepted_text} for the pre-issued token, got HTTP {status}"
    )


async def _assert_cached_token_scenario(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
    action: str,
    expect_revoked: bool,
    admin_mutation: Awaitable[None],
    revoked_statuses: tuple[int, ...] = _TOKEN_REVOKED_STATUSES,
) -> str:
    """Mint once, cache the token, prove it works, then re-probe after admin action."""
    token = await _mint_token_revocation_subject(
        users, oauth, admin_token=admin_token, password=password
    )
    try:
        pre_get = await _self_status(users, token)
        if pre_get != 200:
            raise AssertionError(
                f"RQA-5952: cached token must GET /auth/users/self 200 before "
                f"admin {action}, got HTTP {pre_get}"
            )
        await admin_mutation
        post_get = await _self_status(users, token)
        post_patch = await _patch_self_status(
            users,
            token,
            full_name="Flex Harness UM Cached Token Probe",
        )
        if expect_revoked:
            _assert_token_revoked(
                post_get,
                action=action,
                accepted=revoked_statuses,
                route="GET /auth/users/self",
            )
            _assert_token_revoked(
                post_patch,
                action=action,
                accepted=revoked_statuses,
                route="PATCH /auth/users/self",
            )
            intro_active: bool | None = None
            with contextlib.suppress(RobotApiError):
                intro = await oauth.introspect_token(token)
                intro_active = intro.active
            detail = (
                f"cached token rejected GET {post_get} PATCH {post_patch} "
                f"after admin {action}; introspect active={intro_active}"
            )
        else:
            if post_get != 200:
                raise AssertionError(
                    f"after admin {action}, cached token must still "
                    f"GET /auth/users/self 200, got HTTP {post_get}"
                )
            if post_patch != 200:
                raise AssertionError(
                    f"after admin {action}, cached token must still "
                    f"PATCH /auth/users/self 200, got HTTP {post_patch}"
                )
            detail = (
                f"cached token still GET/PATCH /auth/users/self 200 "
                f"after admin {action}"
            )
        return detail
    finally:
        await _cleanup_token_revocation_users(users, admin_token=admin_token)


async def _token_revoked_after_admin_edit_username(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    async def _mutate() -> None:
        await users.update_user(
            EPHEMERAL_USERNAME_TOKEN_REV,
            UpdateUserRequest(username=EPHEMERAL_USERNAME_TOKEN_REV_REN),
            access_token=admin_token,
        )

    return await _assert_cached_token_scenario(
        users,
        oauth,
        admin_token=admin_token,
        password=password,
        action="edit username",
        expect_revoked=True,
        admin_mutation=_mutate(),
    )


async def _token_revoked_after_admin_edit_role(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    async def _mutate() -> None:
        await users.update_user(
            EPHEMERAL_USERNAME_TOKEN_REV,
            UpdateUserRequest(accountType="auditor"),
            access_token=admin_token,
        )

    return await _assert_cached_token_scenario(
        users,
        oauth,
        admin_token=admin_token,
        password=password,
        action="edit role",
        expect_revoked=True,
        admin_mutation=_mutate(),
    )


async def _token_valid_after_admin_edit_legal_name(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    async def _mutate() -> None:
        await users.update_user(
            EPHEMERAL_USERNAME_TOKEN_REV,
            UpdateUserRequest(fullName="Flex Harness UM Legal"),
            access_token=admin_token,
        )

    return await _assert_cached_token_scenario(
        users,
        oauth,
        admin_token=admin_token,
        password=password,
        action="edit legal name",
        expect_revoked=False,
        admin_mutation=_mutate(),
    )


async def _token_revoked_after_admin_delete_user(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    async def _mutate() -> None:
        await users.delete_user(EPHEMERAL_USERNAME_TOKEN_REV, access_token=admin_token)

    return await _assert_cached_token_scenario(
        users,
        oauth,
        admin_token=admin_token,
        password=password,
        action="delete user",
        expect_revoked=True,
        admin_mutation=_mutate(),
        revoked_statuses=_TOKEN_REVOKED_AFTER_DELETE_STATUSES,
    )


async def _token_revoked_after_admin_lock_account(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    async def _mutate() -> None:
        locked = await users.update_user(
            EPHEMERAL_USERNAME_TOKEN_REV,
            UpdateUserRequest(locked=True),
            access_token=admin_token,
        )
        if not locked.locked:
            raise AssertionError("expected locked=true after admin PATCH")

    return await _assert_cached_token_scenario(
        users,
        oauth,
        admin_token=admin_token,
        password=password,
        action="lock account",
        expect_revoked=True,
        admin_mutation=_mutate(),
    )


async def _token_revoked_after_admin_reset_password(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    async def _mutate() -> None:
        await users.reset_password(
            EPHEMERAL_USERNAME_TOKEN_REV, access_token=admin_token
        )

    return await _assert_cached_token_scenario(
        users,
        oauth,
        admin_token=admin_token,
        password=password,
        action="reset password",
        expect_revoked=True,
        admin_mutation=_mutate(),
    )


class Rqa5952ScenarioResult(BaseModel):
    """One RQA-5952 Gherkin row exercised with a cached pre-minted token."""

    scenario_id: str
    action: str
    expect_revoked: bool
    ok: bool
    detail: str = ""


async def run_rqa5952_token_matrix(
    settings: Settings,
    *,
    admin_username: str = "flex_harness_admin",
) -> list[Rqa5952ScenarioResult]:
    """Run only the RQA-5952 cached-token invalidation matrix."""
    ensure_mutation_allowed(
        settings,
        risk_level=USER_MANAGEMENT_SUITE.risk_level,
        capability_name=USER_MANAGEMENT_SUITE.name,
    )
    password = resolve_ephemeral_password()
    admin_token = await access_token_for_username(settings, admin_username)
    scenarios: list[tuple[str, str, bool, Awaitable[str]]] = []

    async with FlexRobot(settings, access_token=admin_token) as robot:
        users = UsersClient(robot.session)
        oauth = OAuthClient(robot.session)

        async def _wrap(coro: Awaitable[str]) -> str:
            return await coro

        scenarios = [
            (
                "edit_username",
                "edit username",
                True,
                _token_revoked_after_admin_edit_username(
                    users, oauth, admin_token=admin_token, password=password
                ),
            ),
            (
                "edit_role",
                "edit role",
                True,
                _token_revoked_after_admin_edit_role(
                    users, oauth, admin_token=admin_token, password=password
                ),
            ),
            (
                "edit_legal_name",
                "edit legal name",
                False,
                _token_valid_after_admin_edit_legal_name(
                    users, oauth, admin_token=admin_token, password=password
                ),
            ),
            (
                "delete_user",
                "delete user",
                True,
                _token_revoked_after_admin_delete_user(
                    users, oauth, admin_token=admin_token, password=password
                ),
            ),
            (
                "lock_account",
                "lock account",
                True,
                _token_revoked_after_admin_lock_account(
                    users, oauth, admin_token=admin_token, password=password
                ),
            ),
            (
                "reset_password",
                "reset password",
                True,
                _token_revoked_after_admin_reset_password(
                    users, oauth, admin_token=admin_token, password=password
                ),
            ),
        ]

        results: list[Rqa5952ScenarioResult] = []
        for scenario_id, action, expect_revoked, coro in scenarios:
            try:
                detail = await _wrap(coro)
                results.append(
                    Rqa5952ScenarioResult(
                        scenario_id=scenario_id,
                        action=action,
                        expect_revoked=expect_revoked,
                        ok=True,
                        detail=detail,
                    )
                )
            except Exception as exc:
                results.append(
                    Rqa5952ScenarioResult(
                        scenario_id=scenario_id,
                        action=action,
                        expect_revoked=expect_revoked,
                        ok=False,
                        detail=str(exc),
                    )
                )
        robot.raw_evidence["rqa5952_token_matrix"] = [
            item.model_dump(mode="json") for item in results
        ]
        return results


class Rqa5950ProbeStep(BaseModel):
    """One HTTP or introspection probe with the cached pre-rename token."""

    step: str
    http_status: int | None = None
    introspect_active: bool | None = None
    introspect_username: str | None = None
    detail: str = ""


class Rqa5950RetestResult(BaseModel):
    """Outcome for RQA-5950 self-username change with cached session token."""

    subject_username: str
    temp_username: str
    ok: bool
    probes: list[Rqa5950ProbeStep] = Field(default_factory=list)
    detail: str = ""


async def run_rqa5950_retest(
    settings: Settings,
    *,
    admin_username: str = "flex_harness_admin",
    subject_username: str | None = None,
    temp_username: str = EPHEMERAL_USERNAME_SELF_TMP,
    full_name_after_rename: str = "Flex Harness RQA-5950 After Rename",
) -> Rqa5950RetestResult:
    """Retest RQA-5950: cached token must still use self routes after rename."""
    ensure_mutation_allowed(
        settings,
        risk_level=USER_MANAGEMENT_SUITE.risk_level,
        capability_name=USER_MANAGEMENT_SUITE.name,
    )
    spec = EphemeralUserSpec.default()
    if subject_username is not None:
        spec = EphemeralUserSpec(
            username=subject_username,
            password=resolve_ephemeral_password(),
            full_name=spec.full_name,
            account_type=spec.account_type,
        )
    admin_token = await access_token_for_username(settings, admin_username)
    probes: list[Rqa5950ProbeStep] = []

    async def _probe_self(step: str, token: str) -> int:
        status = await _self_status(users, token)
        probes.append(Rqa5950ProbeStep(step=step, http_status=status))
        return status

    async def _probe_patch_full_name(step: str, token: str, full_name: str) -> int:
        status = await _patch_self_status(users, token, full_name=full_name)
        probes.append(Rqa5950ProbeStep(step=step, http_status=status, detail=full_name))
        return status

    async def _probe_introspect(step: str, token: str) -> None:
        with contextlib.suppress(RobotApiError):
            body = await oauth.introspect_token(token)
            probes.append(
                Rqa5950ProbeStep(
                    step=step,
                    introspect_active=body.active,
                    introspect_username=body.username or body.sub,
                )
            )

    async with FlexRobot(settings, access_token=admin_token) as robot:
        users = UsersClient(robot.session)
        oauth = OAuthClient(robot.session)
        await ensure_user_absent(users, temp_username, admin_token=admin_token)
        await ensure_user_present(users, spec, admin_token=admin_token)
        cached_token = await token_for_user(oauth, spec.username, spec.password)

        pre_get = await _probe_self("pre_rename_get_self", cached_token)
        await _probe_introspect("pre_rename_introspect", cached_token)
        if pre_get != 200:
            result = Rqa5950RetestResult(
                subject_username=spec.username,
                temp_username=temp_username,
                ok=False,
                probes=probes,
                detail=(
                    "cached token must GET /auth/users/self 200 before rename, "
                    f"got {pre_get}"
                ),
            )
            robot.raw_evidence["rqa5950_retest"] = result.model_dump(mode="json")
            return result

        await users.update_self(
            UpdateSelfRequest(username=temp_username),
            access_token=cached_token,
        )
        probes.append(
            Rqa5950ProbeStep(
                step="patch_self_username",
                http_status=200,
                detail=temp_username,
            )
        )

        failures: list[str] = []
        try:
            await _probe_introspect("post_rename_introspect_cached_token", cached_token)
            post_get = await _probe_self(
                "post_rename_get_self_cached_token",
                cached_token,
            )
            if post_get != 200:
                failures.append(f"GET /auth/users/self HTTP {post_get}")
            post_patch = await _probe_patch_full_name(
                "post_rename_patch_full_name_cached_token",
                cached_token,
                full_name_after_rename,
            )
            if post_patch != 200:
                failures.append(f"PATCH /auth/users/self fullName HTTP {post_patch}")
        finally:
            reminted = await token_for_user(oauth, temp_username, spec.password)
            restored = await users.update_self(
                UpdateSelfRequest(
                    username=spec.username,
                    fullName=spec.full_name,
                ),
                access_token=reminted,
            )
            if restored.user_name != spec.username:
                failures.append(
                    f"cleanup restore username expected {spec.username!r}, "
                    f"got {restored.user_name!r}"
                )
            await ensure_user_absent(users, temp_username, admin_token=admin_token)

        ok = not failures
        detail = (
            "same-token GET+PATCH /auth/users/self after self username change ok "
            f"(restored {spec.username})"
            if ok
            else "RQA-5950: pre-rename token must still use /auth/users/self after "
            "username change; " + "; ".join(failures)
        )
        result = Rqa5950RetestResult(
            subject_username=spec.username,
            temp_username=temp_username,
            ok=ok,
            probes=probes,
            detail=detail,
        )
        robot.raw_evidence["rqa5950_retest"] = result.model_dump(mode="json")
        return result


async def _patch_self_password(
    users: UsersClient,
    *,
    access_token: str,
    new_password: str,
) -> str:
    updated = await users.update_self(
        UpdateSelfRequest(password=new_password),
        access_token=access_token,
    )
    return f"resetPassword={updated.reset_password}"


async def _introspect(oauth: OAuthClient, token: str) -> str:
    body = await oauth.introspect_token(token)
    subject = body.username or body.sub
    return f"active={body.active} username={subject}"


async def _delete(
    users: UsersClient,
    username: str,
    *,
    admin_token: str,
) -> str:
    await users.delete_user(username, access_token=admin_token)
    return "deleted"


async def _verify_missing(
    users: UsersClient,
    username: str,
    *,
    admin_token: str,
) -> str:
    await verify_user_missing(users, username, admin_token=admin_token)
    return "404 confirmed"


class AccountOnboardingProbeStep(BaseModel):
    """One step in the create → reset → rotate → re-login flow."""

    step: str
    http_status: int | None = None
    ok: bool | None = None
    account_type: str | None = None
    reset_password: bool | None = None
    detail: str = ""


class AccountOnboardingRetestResult(BaseModel):
    """Outcome for temp-password onboarding and post-rotation login."""

    username: str
    account_type: str
    ok: bool
    probes: list[AccountOnboardingProbeStep] = Field(default_factory=list)
    detail: str = ""
    post_rotation_get_self_status: int | None = None


class AccountTypeOnboardingComparisonResult(BaseModel):
    """Compare onboarding flows across CRS account types."""

    results: list[AccountOnboardingRetestResult] = Field(default_factory=list)
    auditor_specific: bool = False
    detail: str = ""


# Backward-compatible aliases for auditor-focused callers.
AuditorOnboardingProbeStep = AccountOnboardingProbeStep
AuditorOnboardingRetestResult = AccountOnboardingRetestResult


async def run_auditor_onboarding_retest(
    settings: Settings,
    *,
    admin_username: str = "flex_harness_admin",
    spec: EphemeralUserSpec | None = None,
    rotated_password: str | None = None,
) -> AccountOnboardingRetestResult:
    """Auditor wrapper for :func:`run_account_onboarding_retest`."""
    return await run_account_onboarding_retest(
        settings,
        admin_username=admin_username,
        spec=spec or EphemeralUserSpec.auditor_default(),
        rotated_password=rotated_password,
    )


async def run_account_type_onboarding_comparison(
    settings: Settings,
    *,
    admin_username: str = "flex_harness_admin",
    account_types: tuple[AccountType, ...] = ("auditor", "user"),
) -> AccountTypeOnboardingComparisonResult:
    """Run onboarding retest for each account type and flag auditor-only failures."""
    results: list[AccountOnboardingRetestResult] = []
    for account_type in account_types:
        spec = EphemeralUserSpec.for_account_type(account_type)
        rotated = resolve_ephemeral_password(
            DEFAULT_AUDITOR_ROTATED_PASSWORD
            if account_type == "auditor"
            else DEFAULT_EPHEMERAL_PASSWORD_ROTATED,
        )
        results.append(
            await run_account_onboarding_retest(
                settings,
                admin_username=admin_username,
                spec=spec,
                rotated_password=rotated,
            )
        )

    by_type = {item.account_type: item for item in results}
    auditor = by_type.get("auditor")
    user = by_type.get("user")
    auditor_self = auditor.post_rotation_get_self_status if auditor else None
    user_self = user.post_rotation_get_self_status if user else None
    auditor_specific = (
        auditor_self == 403
        and user_self == 200
        and auditor is not None
        and user is not None
    )
    if auditor_specific:
        detail = (
            "auditor-specific: GET /auth/users/self returns 403 after password "
            "rotation for auditor but 200 for user"
        )
    elif auditor_self == 403 and user_self == 403:
        detail = (
            "not auditor-specific: both auditor and user GET self 403 after rotation"
        )
    elif auditor_self == 200 and user_self == 200:
        detail = "both auditor and user GET self 200 after rotation"
    else:
        detail = "mixed onboarding results: " + ", ".join(
            f"{item.account_type} get_self={item.post_rotation_get_self_status}"
            for item in results
        )
    return AccountTypeOnboardingComparisonResult(
        results=results,
        auditor_specific=auditor_specific,
        detail=detail,
    )


async def run_account_onboarding_retest(
    settings: Settings,
    *,
    admin_username: str = "flex_harness_admin",
    spec: EphemeralUserSpec | None = None,
    rotated_password: str | None = None,
) -> AccountOnboardingRetestResult:
    """Reproduce onboarding: admin reset, temp login, self rotation, re-login.

    Mirrors manual CRS flow for any ``accountType``:
    1. Admin creates the account
    2. Admin ``POST .../resetPassword`` (user receives temporary password)
    3. User logs in with temporary password (``resetPassword`` still true)
    4. ``PATCH /auth/users/self`` to set a new password
    5. Re-login with the new password and refresh-token rotation
    """
    ensure_mutation_allowed(
        settings,
        risk_level=USER_MANAGEMENT_SUITE.risk_level,
        capability_name="account_onboarding_retest",
    )
    subject = spec or EphemeralUserSpec.auditor_default()
    default_rotated = (
        DEFAULT_AUDITOR_ROTATED_PASSWORD
        if subject.account_type == "auditor"
        else DEFAULT_EPHEMERAL_PASSWORD_ROTATED
    )
    new_password = rotated_password or resolve_ephemeral_password(default_rotated)
    admin_token = await access_token_for_username(settings, admin_username)
    probes: list[AccountOnboardingProbeStep] = []
    failures: list[str] = []
    post_rotation_get_self_status: int | None = None
    expected_account_type = subject.account_type

    async def _probe_ropc(
        step: str,
        username: str,
        password: str,
        *,
        expect_ok: bool,
    ) -> TokenResponse | None:
        try:
            token_response = await oauth.get_token(username, password)
        except RobotApiError as exc:
            probes.append(
                AccountOnboardingProbeStep(
                    step=step,
                    http_status=exc.status_code,
                    ok=False,
                    detail=str(exc) or "ROPC rejected",
                )
            )
            if expect_ok:
                failures.append(f"{step}: expected ROPC 200, got {exc.status_code}")
            return None
        refresh_note = (
            "refresh_token issued"
            if token_response.refresh_token
            else "refresh_token omitted"
        )
        probes.append(
            AccountOnboardingProbeStep(
                step=step,
                http_status=200,
                ok=True,
                detail=f"access_token minted; {refresh_note}",
            )
        )
        if not expect_ok:
            failures.append(f"{step}: expected ROPC rejection, got 200")
        return token_response

    async def _probe_refresh(
        step: str,
        refresh_token: str,
        *,
        expect_ok: bool,
    ) -> TokenResponse | None:
        try:
            token_response = await oauth.refresh_access_token(refresh_token)
        except RobotApiError as exc:
            probes.append(
                AccountOnboardingProbeStep(
                    step=step,
                    http_status=exc.status_code,
                    ok=False,
                    detail=str(exc) or "refresh rejected",
                )
            )
            if expect_ok:
                failures.append(
                    f"{step}: expected refresh 200, got {exc.status_code}",
                )
            return None
        probes.append(
            AccountOnboardingProbeStep(
                step=step,
                http_status=200,
                ok=True,
                detail="access_token minted via refresh_token grant",
            )
        )
        if not expect_ok:
            failures.append(f"{step}: expected refresh rejection, got 200")
        return token_response

    async with FlexRobot(settings, access_token=admin_token) as robot:
        users = UsersClient(robot.session)
        oauth = OAuthClient(robot.session)

        await ensure_user_absent(users, subject.username, admin_token=admin_token)
        created = await users.create_user(
            username=subject.username,
            password=subject.password,
            full_name=subject.full_name,
            account_type=subject.account_type,
            access_token=admin_token,
        )
        probes.append(
            AccountOnboardingProbeStep(
                step="create_user",
                http_status=201,
                ok=True,
                account_type=created.account_type,
                reset_password=created.reset_password,
                detail=f"username={created.user_name}",
            )
        )
        if created.account_type != expected_account_type:
            failures.append(
                f"create_user: expected accountType={expected_account_type!r}, "
                f"got {created.account_type!r}",
            )

        reset = await users.reset_password(
            subject.username,
            access_token=admin_token,
        )
        probes.append(
            AccountOnboardingProbeStep(
                step="admin_reset_password",
                http_status=200,
                ok=True,
                account_type=reset.account_type,
                reset_password=reset.reset_password,
                detail="temporaryPassword=<redacted>",
            )
        )
        if not reset.reset_password:
            failures.append("admin_reset_password: expected resetPassword=true")
        if reset.account_type != expected_account_type:
            failures.append(
                "admin_reset_password: "
                f"expected accountType={expected_account_type!r}, "
                f"got {reset.account_type!r}",
            )

        temp_login = await _probe_ropc(
            "login_temp_password",
            subject.username,
            reset.temporary_password,
            expect_ok=True,
        )
        temp_token = temp_login.access_token if temp_login is not None else None
        temp_refresh = temp_login.refresh_token if temp_login is not None else None
        if temp_token is not None:
            profile = await users.get_self(access_token=temp_token)
            probes.append(
                AccountOnboardingProbeStep(
                    step="get_self_with_temp_login",
                    http_status=200,
                    ok=True,
                    account_type=profile.account_type,
                    reset_password=profile.reset_password,
                )
            )
            if not profile.reset_password:
                failures.append(
                    "get_self_with_temp_login: expected resetPassword=true "
                    "before rotation",
                )

            updated = await users.update_self(
                UpdateSelfRequest(password=new_password),
                access_token=temp_token,
            )
            probes.append(
                AccountOnboardingProbeStep(
                    step="patch_self_new_password",
                    http_status=200,
                    ok=True,
                    account_type=updated.account_type,
                    reset_password=updated.reset_password,
                )
            )
            if updated.reset_password:
                failures.append(
                    "patch_self_new_password: expected resetPassword=false "
                    "after rotation",
                )

        await _probe_ropc(
            "login_original_password_rejected",
            subject.username,
            subject.password,
            expect_ok=False,
        )
        await _probe_ropc(
            "login_temp_password_rejected",
            subject.username,
            reset.temporary_password,
            expect_ok=False,
        )
        if temp_refresh:
            await _probe_refresh(
                "refresh_temp_password_token_rejected",
                temp_refresh,
                expect_ok=False,
            )
        else:
            probes.append(
                AccountOnboardingProbeStep(
                    step="refresh_temp_password_token_rejected",
                    ok=None,
                    detail="skipped: temp login omitted refresh_token",
                )
            )

        new_login = await _probe_ropc(
            "login_new_password",
            subject.username,
            new_password,
            expect_ok=True,
        )
        if new_login is not None:
            try:
                ropc_profile = await users.get_self(access_token=new_login.access_token)
            except RobotApiError as exc:
                post_rotation_get_self_status = exc.status_code
                probes.append(
                    AccountOnboardingProbeStep(
                        step="get_self_with_new_password_ropc_token",
                        http_status=exc.status_code,
                        ok=False,
                        detail=str(exc),
                    )
                )
                failures.append(
                    "get_self_with_new_password_ropc_token: "
                    f"expected 200, got {exc.status_code}",
                )
            else:
                post_rotation_get_self_status = 200
                probes.append(
                    AccountOnboardingProbeStep(
                        step="get_self_with_new_password_ropc_token",
                        http_status=200,
                        ok=True,
                        account_type=ropc_profile.account_type,
                        reset_password=ropc_profile.reset_password,
                    )
                )

        repeat_login = await _probe_ropc(
            "login_new_password_repeat",
            subject.username,
            new_password,
            expect_ok=True,
        )
        new_token = repeat_login.access_token if repeat_login is not None else None
        if new_token is not None:
            intro = await oauth.introspect_token(new_token)
            probes.append(
                AccountOnboardingProbeStep(
                    step="introspect_new_password_token",
                    ok=intro.active,
                    detail=(
                        f"active={intro.active} "
                        f"username={intro.username or intro.sub} "
                        f"scope={intro.scope!r}"
                    ),
                )
            )
            if not intro.active:
                failures.append("introspect_new_password_token: expected active=true")

        new_refresh = new_login.refresh_token if new_login is not None else None
        if new_login is not None and not new_refresh:
            failures.append(
                "login_new_password: expected refresh_token in ROPC response "
                "(App session rotation depends on it)",
            )
        if new_refresh:
            refreshed = await _probe_refresh(
                "refresh_new_password_token",
                new_refresh,
                expect_ok=True,
            )
            if refreshed is not None:
                try:
                    intro = await oauth.introspect_token(refreshed.access_token)
                except RobotApiError as exc:
                    probes.append(
                        AccountOnboardingProbeStep(
                            step="introspect_refreshed_access_token",
                            http_status=exc.status_code,
                            ok=False,
                            detail=str(exc),
                        )
                    )
                    failures.append(
                        "introspect_refreshed_access_token: "
                        f"expected 200, got {exc.status_code}",
                    )
                else:
                    probes.append(
                        AccountOnboardingProbeStep(
                            step="introspect_refreshed_access_token",
                            ok=intro.active,
                            detail=(
                                f"active={intro.active} "
                                f"username={intro.username or intro.sub} "
                                f"scope={intro.scope!r}"
                            ),
                        )
                    )
                    if not intro.active:
                        failures.append(
                            "introspect_refreshed_access_token: expected active=true",
                        )
                try:
                    profile = await users.get_self(access_token=refreshed.access_token)
                except RobotApiError as exc:
                    probes.append(
                        AccountOnboardingProbeStep(
                            step="get_self_with_refreshed_token",
                            http_status=exc.status_code,
                            ok=False,
                            detail=str(exc),
                        )
                    )
                    failures.append(
                        "get_self_with_refreshed_token: "
                        f"expected 200, got {exc.status_code}",
                    )
                else:
                    probes.append(
                        AccountOnboardingProbeStep(
                            step="get_self_with_refreshed_token",
                            http_status=200,
                            ok=True,
                            account_type=profile.account_type,
                            reset_password=profile.reset_password,
                        )
                    )
                    if profile.account_type != expected_account_type:
                        failures.append(
                            "get_self_with_refreshed_token: "
                            f"expected accountType={expected_account_type!r}",
                        )
                    if profile.reset_password:
                        failures.append(
                            "get_self_with_refreshed_token: "
                            "expected resetPassword=false",
                        )

        await ensure_user_absent(users, subject.username, admin_token=admin_token)
        probes.append(
            AccountOnboardingProbeStep(
                step="cleanup_delete_user",
                http_status=200,
                ok=True,
            )
        )

        ok = not failures
        detail = (
            f"{subject.account_type} temp-password onboarding, post-rotation ROPC, "
            "and refresh ok"
            if ok
            else f"{subject.account_type} onboarding bug: " + "; ".join(failures)
        )
        result = AccountOnboardingRetestResult(
            username=subject.username,
            account_type=subject.account_type,
            ok=ok,
            probes=probes,
            detail=detail,
            post_rotation_get_self_status=post_rotation_get_self_status,
        )
        robot.raw_evidence[f"onboarding_retest_{subject.account_type}"] = (
            result.model_dump(mode="json")
        )
        return result
