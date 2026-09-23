"""Orchestrated desktop app scenarios."""

from __future__ import annotations

from dataclasses import dataclass

from playwright.sync_api import Page

from flex_testing_agent.app_cdp.connect import (
    AppCdpConnection,
    attach_to_app,
    launch_and_attach,
)
from flex_testing_agent.app_cdp.pages.login_modal import LoginOutcome
from flex_testing_agent.app_cdp.scenarios.compliance_common import (
    login_with_admin_candidates,
)
from flex_testing_agent.app_cdp.screenplay.actor import Actor
from flex_testing_agent.app_cdp.screenplay.tasks import OpenComplianceUsers
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.crs_users import (
    AdminLoginCandidate,
    admin_login_candidates,
    expected_compliance_ui_usernames,
)


@dataclass(frozen=True)
class ComplianceUsersValidationResult:
    """Compare visible App usernames to fixture expectations."""

    expected: tuple[str, ...]
    visible: tuple[str, ...]
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.unexpected


@dataclass(frozen=True)
class ComplianceUsersScenarioResult:
    robot_name: str
    admin_username: str
    login_outcome: LoginOutcome
    password_reset_performed: bool
    locked_admin_candidates: tuple[str, ...]
    usernames: tuple[str, ...]
    validation: ComplianceUsersValidationResult


def validate_compliance_users(
    visible: list[str],
    *,
    allow_extra: bool = False,
) -> ComplianceUsersValidationResult:
    """Return missing and unexpected usernames vs crs_users.yaml fixtures."""
    expected = tuple(expected_compliance_ui_usernames())
    visible_tuple = tuple(visible)
    expected_set = set(expected)
    visible_set = set(visible)
    missing = tuple(sorted(expected_set - visible_set))
    unexpected: tuple[str, ...] = ()
    if not allow_extra:
        unexpected = tuple(sorted(visible_set - expected_set))
    return ComplianceUsersValidationResult(
        expected=expected,
        visible=visible_tuple,
        missing=missing,
        unexpected=unexpected,
    )


def run_compliance_users_scenario(
    page: Page,
    *,
    settings: Settings,
    admin_username: str | None = None,
    admin_password: str | None = None,
    admin_password_alt: str | None = None,
    allow_extra_users: bool = False,
) -> ComplianceUsersScenarioResult:
    """Log in as admin, open compliance settings, list and validate users."""
    robot_name = settings.robot_name

    if admin_username and admin_password and admin_password_alt:
        candidates = [
            AdminLoginCandidate(
                username=admin_username,
                primary_password=admin_password,
                alternate_password=admin_password_alt,
            )
        ]
    else:
        candidates = admin_login_candidates(settings)

    actor = Actor(page=page, name=candidates[0].username)
    login_task, locked = login_with_admin_candidates(actor, robot_name, candidates)
    result = login_task.result
    assert result is not None

    users_task = OpenComplianceUsers(robot_name)
    actor.attempts_to(users_task)
    validation = validate_compliance_users(
        users_task.usernames,
        allow_extra=allow_extra_users,
    )

    return ComplianceUsersScenarioResult(
        robot_name=robot_name,
        admin_username=login_task.username,
        login_outcome=result.outcome,
        password_reset_performed=login_task.password_reset_performed,
        locked_admin_candidates=tuple(locked),
        usernames=tuple(users_task.usernames),
        validation=validation,
    )


def run_compliance_users_with_cdp(
    settings: Settings,
    *,
    attach_only: bool = False,
) -> tuple[ComplianceUsersScenarioResult, AppCdpConnection]:
    """Launch or attach to the app, run the scenario, and return the connection."""
    connection = attach_to_app() if attach_only else launch_and_attach(quiet=True)
    try:
        result = run_compliance_users_scenario(connection.page, settings=settings)
    except Exception:
        connection.close()
        raise
    return result, connection
