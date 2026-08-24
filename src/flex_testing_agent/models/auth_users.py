"""Auth-server user and OAuth models (CRS-on)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AccountType = Literal["admin", "user", "auditor", "service"]


class TokenResponse(BaseModel):
    """Successful ROPC token response."""

    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str | None = None
    scope: str = ""


class TokenIntrospectionResponse(BaseModel):
    """RFC 7662 introspection response (active tokens only)."""

    model_config = ConfigDict(extra="allow")

    active: bool
    username: str | None = None
    sub: str | None = None
    scope: str | None = None
    client_id: str | None = None
    exp: int | None = None
    iat: int | None = None
    token_type: str | None = None


class UserCreateRequest(BaseModel):
    """POST /auth/users body ``data`` object."""

    model_config = ConfigDict(populate_by_name=True)

    username: str
    password: str
    full_name: str = Field(alias="fullName")
    account_type: AccountType = Field(alias="accountType")


class UpdateUserRequest(BaseModel):
    """PATCH /auth/users/byUsername/{username} body ``data`` object."""

    model_config = ConfigDict(populate_by_name=True)

    username: str | None = None
    password: str | None = None
    full_name: str | None = Field(default=None, alias="fullName")
    account_type: AccountType | None = Field(default=None, alias="accountType")
    locked: bool | None = None
    reset_password: Literal[True] | None = Field(default=None, alias="resetPassword")

    def to_json_api(self) -> dict[str, Any]:
        """Return JSON-API payload omitting unset fields."""
        raw = self.model_dump(by_alias=True, exclude_none=True)
        return raw


class UpdateSelfRequest(BaseModel):
    """PATCH /auth/users/self body ``data`` object."""

    model_config = ConfigDict(populate_by_name=True)

    username: str | None = None
    full_name: str | None = Field(default=None, alias="fullName")
    password: str | None = None

    def to_json_api(self) -> dict[str, Any]:
        raw = self.model_dump(by_alias=True, exclude_none=True)
        return raw


class UserResponse(BaseModel):
    """User resource inside auth-server envelopes."""

    model_config = ConfigDict(populate_by_name=True)

    user_name: str = Field(alias="username")
    full_name: str = Field(alias="fullName")
    account_type: AccountType = Field(alias="accountType")
    scopes: list[str] = Field(default_factory=list)
    locked: bool
    reset_password: bool = Field(alias="resetPassword")


class ResetPasswordResponse(UserResponse):
    """Password reset includes a generated temporary password."""

    temporary_password: str = Field(alias="temporaryPassword")


class UserResourceResponse(BaseModel):
    """``{"data": {...}}`` wrapper for single-user responses."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    data: UserResponse


class ResetPasswordResourceResponse(BaseModel):
    """``{"data": {...}}`` wrapper for reset-password responses."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    data: ResetPasswordResponse
