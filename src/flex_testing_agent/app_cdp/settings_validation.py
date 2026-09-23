"""Compare Compliance Ready App settings UI to robot HTTP API snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flex_testing_agent.models.auth_settings import AuthSettingsData


@dataclass(frozen=True, slots=True)
class AppAuthSettingsSnapshot:
    """Auth settings visible in the App Compliance Ready Software settings panel."""

    max_number_of_login_attempts: int
    password_reset_enabled: bool
    password_reset_time: float | None
    password_complexity_enabled: bool
    password_complexity_minimum_length: int | None
    password_complexity_special_characters: bool | None
    idle_logout_minutes: float
    require_admin_creds_when_updating_robot_software: bool
    require_admin_creds_when_sending_protocol_to_robot: bool
    require_admin_creds_for_signoff_protocol: bool


@dataclass(frozen=True, slots=True)
class AppAuditSettingsSnapshot:
    """Audit settings visible in the same App panel (audit-server API)."""

    require_reason_for_interaction: bool


@dataclass(frozen=True, slots=True)
class SettingsFieldMismatch:
    field: str
    ui_value: str
    api_value: str


@dataclass(frozen=True, slots=True)
class ComplianceSettingsValidationResult:
    auth_mismatches: tuple[SettingsFieldMismatch, ...]
    audit_mismatches: tuple[SettingsFieldMismatch, ...]

    @property
    def ok(self) -> bool:
        return not self.auth_mismatches and not self.audit_mismatches


def _mismatch(
    field: str,
    ui_value: object,
    api_value: object,
) -> SettingsFieldMismatch:
    return SettingsFieldMismatch(
        field=field,
        ui_value=str(ui_value),
        api_value=str(api_value),
    )


def validate_auth_settings_against_api(
    ui: AppAuthSettingsSnapshot,
    api: AuthSettingsData,
) -> tuple[SettingsFieldMismatch, ...]:
    """Return UI vs GET /auth/settings mismatches (empty when aligned)."""
    mismatches: list[SettingsFieldMismatch] = []

    if ui.max_number_of_login_attempts != api.max_number_of_login_attempts:
        mismatches.append(
            _mismatch(
                "maxNumberOfLoginAttempts",
                ui.max_number_of_login_attempts,
                api.max_number_of_login_attempts,
            )
        )

    api_password_reset_enabled = api.password_reset_time is not None
    if ui.password_reset_enabled != api_password_reset_enabled:
        mismatches.append(
            _mismatch(
                "passwordResetEnabled",
                ui.password_reset_enabled,
                api_password_reset_enabled,
            )
        )
    elif (
        ui.password_reset_enabled and ui.password_reset_time != api.password_reset_time
    ):
        mismatches.append(
            _mismatch(
                "passwordResetTime",
                ui.password_reset_time,
                api.password_reset_time,
            )
        )

    api_complexity_enabled = (
        api.password_complexity_minimum_length is not None
        or api.password_complexity_special_characters is not None
    )
    if ui.password_complexity_enabled != api_complexity_enabled:
        mismatches.append(
            _mismatch(
                "passwordComplexityEnabled",
                ui.password_complexity_enabled,
                api_complexity_enabled,
            )
        )
    elif ui.password_complexity_enabled:
        ui_min = ui.password_complexity_minimum_length
        api_min = api.password_complexity_minimum_length
        if ui_min != api_min:
            mismatches.append(
                _mismatch(
                    "passwordComplexityMinimumLength",
                    ui.password_complexity_minimum_length,
                    api.password_complexity_minimum_length,
                )
            )
        if (
            ui.password_complexity_special_characters
            != api.password_complexity_special_characters
        ):
            mismatches.append(
                _mismatch(
                    "passwordComplexitySpecialCharacters",
                    ui.password_complexity_special_characters,
                    api.password_complexity_special_characters,
                )
            )

    api_idle_minutes = api.idle_logout / 60.0
    if abs(ui.idle_logout_minutes - api_idle_minutes) > 0.01:
        mismatches.append(
            _mismatch(
                "idleLogout (minutes)",
                ui.idle_logout_minutes,
                api_idle_minutes,
            )
        )

    toggle_fields: tuple[tuple[str, bool, bool], ...] = (
        (
            "requireAdminCredsWhenUpdatingRobotSoftware",
            ui.require_admin_creds_when_updating_robot_software,
            api.require_admin_creds_when_updating_robot_software,
        ),
        (
            "requireAdminCredsWhenSendingProtocolToRobot",
            ui.require_admin_creds_when_sending_protocol_to_robot,
            api.require_admin_creds_when_sending_protocol_to_robot,
        ),
        (
            "requireAdminCredsForSignoffProtocol",
            ui.require_admin_creds_for_signoff_protocol,
            api.require_admin_creds_for_signoff_protocol,
        ),
    )
    for field, ui_value, api_value in toggle_fields:
        if ui_value != api_value:
            mismatches.append(_mismatch(field, ui_value, api_value))

    return tuple(mismatches)


def validate_audit_settings_against_api(
    ui: AppAuditSettingsSnapshot,
    audit_data: dict[str, Any],
) -> tuple[SettingsFieldMismatch, ...]:
    """Return UI vs GET /audit/external/settings mismatches."""
    api_value = audit_data.get("requireReasonForInteraction")
    if api_value is None:
        return ()
    if bool(ui.require_reason_for_interaction) != bool(api_value):
        return (
            _mismatch(
                "requireReasonForInteraction",
                ui.require_reason_for_interaction,
                api_value,
            ),
        )
    return ()
