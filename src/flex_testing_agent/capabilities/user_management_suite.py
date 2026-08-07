"""CRS-on user-management API coverage (all auth-server user verbs)."""

from __future__ import annotations

from collections.abc import Awaitable

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.clients.users import UsersClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.user_management import (
    DEFAULT_EPHEMERAL_PASSWORD_ROTATED,
    EPHEMERAL_USERNAME_RENAMED,
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

USER_MANAGEMENT_SUITE = CapabilityDescriptor(
    name="crs_on_user_management",
    description=(
        "CRS-on auth-server user CRUD suite: POST/GET/PATCH/DELETE users, "
        "resetPassword, self routes, and OAuth introspect. Idempotent setup "
        "creates a throwaway flex_harness_um_crud account."
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
) -> UserManagementSuiteResult:
    """Run idempotent user-management API coverage on a CRS-enabled robot."""
    ensure_mutation_allowed(
        settings,
        risk_level=USER_MANAGEMENT_SUITE.risk_level,
        capability_name=USER_MANAGEMENT_SUITE.name,
    )
    spec = EphemeralUserSpec.default()
    admin_token = await access_token_for_username(settings, admin_username)

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
