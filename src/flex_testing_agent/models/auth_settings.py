"""Auth-server policy settings (GET/PATCH /auth/settings)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuthSettingsData(BaseModel):
    """Policy object inside ``GET /auth/settings`` ``data``."""

    model_config = ConfigDict(populate_by_name=True)

    max_number_of_login_attempts: int = Field(alias="maxNumberOfLoginAttempts")
    password_reset_time: float | None = Field(default=None, alias="passwordResetTime")
    password_complexity_minimum_length: int | None = Field(
        default=None,
        alias="passwordComplexityMinimumLength",
    )
    password_complexity_special_characters: bool | None = Field(
        default=None,
        alias="passwordComplexitySpecialCharacters",
    )
    idle_logout: float = Field(alias="idleLogout")
    require_admin_creds_when_updating_robot_software: bool = Field(
        alias="requireAdminCredsWhenUpdatingRobotSoftware",
    )
    require_admin_creds_when_sending_protocol_to_robot: bool = Field(
        alias="requireAdminCredsWhenSendingProtocolToRobot",
    )
    require_admin_creds_for_signoff_protocol: bool = Field(
        alias="requireAdminCredsForSignoffProtocol",
    )

    def patch_fields(self) -> dict[str, Any]:
        """Return a PATCH ``data`` object including explicit nulls."""
        return self.model_dump(by_alias=True, mode="json")


class AuthSettingsPatch(BaseModel):
    """Partial PATCH body for ``/auth/settings``."""

    model_config = ConfigDict(populate_by_name=True)

    max_number_of_login_attempts: int | None = Field(
        default=None,
        alias="maxNumberOfLoginAttempts",
    )
    password_reset_time: float | None = Field(
        default=None,
        alias="passwordResetTime",
    )
    password_complexity_minimum_length: int | None = Field(
        default=None,
        alias="passwordComplexityMinimumLength",
    )
    password_complexity_special_characters: bool | None = Field(
        default=None,
        alias="passwordComplexitySpecialCharacters",
    )
    idle_logout: float | None = Field(default=None, alias="idleLogout")
    require_admin_creds_when_updating_robot_software: bool | None = Field(
        default=None,
        alias="requireAdminCredsWhenUpdatingRobotSoftware",
    )
    require_admin_creds_when_sending_protocol_to_robot: bool | None = Field(
        default=None,
        alias="requireAdminCredsWhenSendingProtocolToRobot",
    )
    require_admin_creds_for_signoff_protocol: bool | None = Field(
        default=None,
        alias="requireAdminCredsForSignoffProtocol",
    )

    def to_request_body(self) -> dict[str, dict[str, Any]]:
        raw = self.model_dump(by_alias=True, exclude_none=True)
        return {"data": raw}


class AuthSettingsResourceResponse(BaseModel):
    """``{"data": {...}}`` wrapper for auth settings."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    data: AuthSettingsData
