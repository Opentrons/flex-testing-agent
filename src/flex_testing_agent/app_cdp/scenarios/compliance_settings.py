"""App Compliance Ready settings UI vs robot API validation scenario."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Page

from flex_testing_agent.app_cdp.api_snapshots import fetch_settings_snapshots_sync
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
from flex_testing_agent.app_cdp.settings_validation import (
    AppAuditSettingsSnapshot,
    AppAuthSettingsSnapshot,
    ComplianceSettingsValidationResult,
    SettingsFieldMismatch,
    validate_audit_settings_against_api,
    validate_auth_settings_against_api,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.crs_users import (
    AdminLoginCandidate,
    admin_login_candidates,
)
from flex_testing_agent.models.auth_settings import AuthSettingsData


@dataclass(frozen=True)
class ComplianceSettingsScenarioResult:
    robot_name: str
    admin_username: str
    login_outcome: LoginOutcome
    password_reset_performed: bool
    locked_admin_candidates: tuple[str, ...]
    ui_auth: AppAuthSettingsSnapshot
    ui_audit: AppAuditSettingsSnapshot
    api_auth: AuthSettingsData
    api_audit: dict[str, Any]
    validation: ComplianceSettingsValidationResult


def run_compliance_settings_scenario(
    page: Page,
    *,
    settings: Settings,
    admin_username: str | None = None,
    admin_password: str | None = None,
    admin_password_alt: str | None = None,
) -> ComplianceSettingsScenarioResult:
    """Log in, expand software settings, and compare App UI to robot APIs."""
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
    login_result = login_task.result
    assert login_result is not None

    actor.compliance.open(robot_name)
    actor.compliance.open_software_settings()
    ui_auth = actor.compliance.read_auth_settings_snapshot()
    ui_audit = actor.compliance.read_audit_settings_snapshot()

    api_auth, api_audit = fetch_settings_snapshots_sync(
        settings,
        login_task.username,
    )
    auth_mismatches = validate_auth_settings_against_api(ui_auth, api_auth)
    audit_mismatches = validate_audit_settings_against_api(ui_audit, api_audit)
    validation = ComplianceSettingsValidationResult(
        auth_mismatches=auth_mismatches,
        audit_mismatches=audit_mismatches,
    )

    return ComplianceSettingsScenarioResult(
        robot_name=robot_name,
        admin_username=login_task.username,
        login_outcome=login_result.outcome,
        password_reset_performed=login_task.password_reset_performed,
        locked_admin_candidates=tuple(locked),
        ui_auth=ui_auth,
        ui_audit=ui_audit,
        api_auth=api_auth,
        api_audit=api_audit,
        validation=validation,
    )


def run_compliance_settings_with_cdp(
    settings: Settings,
    *,
    attach_only: bool = False,
) -> tuple[ComplianceSettingsScenarioResult, AppCdpConnection]:
    """Launch or attach to the app and run the settings validation scenario."""
    connection = attach_to_app() if attach_only else launch_and_attach(quiet=True)
    try:
        result = run_compliance_settings_scenario(connection.page, settings=settings)
    except Exception:
        connection.close()
        raise
    return result, connection


def format_mismatches(
    mismatches: tuple[SettingsFieldMismatch, ...],
) -> str:
    if not mismatches:
        return "(none)"
    return "; ".join(
        f"{item.field}: ui={item.ui_value} api={item.api_value}" for item in mismatches
    )
