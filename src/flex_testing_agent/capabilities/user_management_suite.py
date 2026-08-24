"""CRS-on user-management API coverage (all auth-server user verbs)."""

from __future__ import annotations

from collections.abc import Awaitable

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.clients.users import UsersClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.user_management import (
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
from flex_testing_agent.models.auth_users import UpdateSelfRequest, UpdateUserRequest
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


def _assert_token_revoked(
    status: int, *, action: str, accepted: tuple[int, ...]
) -> str:
    if status in accepted:
        return f"GET /auth/users/self HTTP {status} after admin {action}"
    accepted_text = "/".join(str(code) for code in accepted)
    raise AssertionError(
        f"RQA-5952: after admin {action}, expected GET /auth/users/self "
        f"{accepted_text} for the pre-issued token, got HTTP {status}"
    )


async def _token_revoked_after_admin_edit_username(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    token = await _mint_token_revocation_subject(
        users, oauth, admin_token=admin_token, password=password
    )
    try:
        await users.update_user(
            EPHEMERAL_USERNAME_TOKEN_REV,
            UpdateUserRequest(username=EPHEMERAL_USERNAME_TOKEN_REV_REN),
            access_token=admin_token,
        )
        status = await _self_status(users, token)
        return _assert_token_revoked(
            status, action="edit username", accepted=_TOKEN_REVOKED_STATUSES
        )
    finally:
        await _cleanup_token_revocation_users(users, admin_token=admin_token)


async def _token_revoked_after_admin_edit_role(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    token = await _mint_token_revocation_subject(
        users, oauth, admin_token=admin_token, password=password
    )
    try:
        await users.update_user(
            EPHEMERAL_USERNAME_TOKEN_REV,
            UpdateUserRequest(accountType="auditor"),
            access_token=admin_token,
        )
        status = await _self_status(users, token)
        return _assert_token_revoked(
            status, action="edit role", accepted=_TOKEN_REVOKED_STATUSES
        )
    finally:
        await _cleanup_token_revocation_users(users, admin_token=admin_token)


async def _token_valid_after_admin_edit_legal_name(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    token = await _mint_token_revocation_subject(
        users, oauth, admin_token=admin_token, password=password
    )
    try:
        await users.update_user(
            EPHEMERAL_USERNAME_TOKEN_REV,
            UpdateUserRequest(fullName="Flex Harness UM Legal"),
            access_token=admin_token,
        )
        status = await _self_status(users, token)
        if status == 200:
            return "GET /auth/users/self HTTP 200 after admin edit legal name"
        raise AssertionError(
            "after admin edit legal name, pre-issued token must still "
            f"GET /auth/users/self 200, got HTTP {status}"
        )
    finally:
        await _cleanup_token_revocation_users(users, admin_token=admin_token)


async def _token_revoked_after_admin_delete_user(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    token = await _mint_token_revocation_subject(
        users, oauth, admin_token=admin_token, password=password
    )
    try:
        await users.delete_user(EPHEMERAL_USERNAME_TOKEN_REV, access_token=admin_token)
        status = await _self_status(users, token)
        return _assert_token_revoked(
            status,
            action="delete user",
            accepted=_TOKEN_REVOKED_AFTER_DELETE_STATUSES,
        )
    finally:
        await _cleanup_token_revocation_users(users, admin_token=admin_token)


async def _token_revoked_after_admin_lock_account(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    token = await _mint_token_revocation_subject(
        users, oauth, admin_token=admin_token, password=password
    )
    try:
        locked = await users.update_user(
            EPHEMERAL_USERNAME_TOKEN_REV,
            UpdateUserRequest(locked=True),
            access_token=admin_token,
        )
        if not locked.locked:
            raise AssertionError("expected locked=true after admin PATCH")
        status = await _self_status(users, token)
        return _assert_token_revoked(
            status, action="lock account", accepted=_TOKEN_REVOKED_STATUSES
        )
    finally:
        await _cleanup_token_revocation_users(users, admin_token=admin_token)


async def _token_revoked_after_admin_reset_password(
    users: UsersClient,
    oauth: OAuthClient,
    *,
    admin_token: str,
    password: str,
) -> str:
    token = await _mint_token_revocation_subject(
        users, oauth, admin_token=admin_token, password=password
    )
    try:
        await users.reset_password(
            EPHEMERAL_USERNAME_TOKEN_REV, access_token=admin_token
        )
        status = await _self_status(users, token)
        return _assert_token_revoked(
            status, action="reset password", accepted=_TOKEN_REVOKED_STATUSES
        )
    finally:
        await _cleanup_token_revocation_users(users, admin_token=admin_token)


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
