"""Auth-server user CRUD client (CRS-on provisioning and tests)."""

from __future__ import annotations

from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.models.auth_users import (
    AccountType,
    ResetPasswordResourceResponse,
    ResetPasswordResponse,
    UpdateSelfRequest,
    UpdateUserRequest,
    UserResourceResponse,
    UserResponse,
)


class UsersClient:
    """Atomic client for ``/auth/users`` endpoints."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    @staticmethod
    def _user_path(username: str) -> str:
        return f"/auth/users/byUsername/{username}"

    async def create_user(
        self,
        *,
        username: str,
        password: str,
        full_name: str,
        account_type: AccountType,
        access_token: str | None = None,
        timeout: float | None = None,
    ) -> UserResponse:
        """POST /auth/users (requires admin token when CRS on)."""
        body = {
            "data": {
                "username": username,
                "password": password,
                "fullName": full_name,
                "accountType": account_type,
            }
        }
        payload = await self._session.post_json(
            "/auth/users",
            json_body=body,
            timeout=timeout,
            expected_status=(201,),
            extra_headers=_bearer_headers(access_token),
        )
        envelope = UserResourceResponse.model_validate(payload)
        return envelope.data

    async def get_user_by_username(
        self,
        username: str,
        *,
        access_token: str,
        timeout: float | None = None,
    ) -> UserResponse:
        """GET /auth/users/byUsername/{username}."""
        payload = await self._session.get_json(
            self._user_path(username),
            timeout=timeout,
            extra_headers=_bearer_headers(access_token),
        )
        envelope = UserResourceResponse.model_validate(payload)
        return envelope.data

    async def get_self(
        self,
        *,
        access_token: str,
        timeout: float | None = None,
    ) -> UserResponse:
        """GET /auth/users/self."""
        payload = await self._session.get_json(
            "/auth/users/self",
            timeout=timeout,
            extra_headers=_bearer_headers(access_token),
        )
        envelope = UserResourceResponse.model_validate(payload)
        return envelope.data

    async def update_user(
        self,
        username: str,
        update: UpdateUserRequest,
        *,
        access_token: str,
        timeout: float | None = None,
    ) -> UserResponse:
        """PATCH /auth/users/byUsername/{username}."""
        payload = await self._session.patch_json(
            self._user_path(username),
            json_body={"data": update.to_json_api()},
            timeout=timeout,
            extra_headers=_bearer_headers(access_token),
        )
        envelope = UserResourceResponse.model_validate(payload)
        return envelope.data

    async def update_self(
        self,
        update: UpdateSelfRequest,
        *,
        access_token: str,
        timeout: float | None = None,
    ) -> UserResponse:
        """PATCH /auth/users/self."""
        payload = await self._session.patch_json(
            "/auth/users/self",
            json_body={"data": update.to_json_api()},
            timeout=timeout,
            extra_headers=_bearer_headers(access_token),
        )
        envelope = UserResourceResponse.model_validate(payload)
        return envelope.data

    async def reset_password(
        self,
        username: str,
        *,
        access_token: str,
        timeout: float | None = None,
    ) -> ResetPasswordResponse:
        """POST /auth/users/byUsername/{username}/resetPassword."""
        payload = await self._session.post_json(
            f"{self._user_path(username)}/resetPassword",
            json_body={"data": {}},
            timeout=timeout,
            extra_headers=_bearer_headers(access_token),
        )
        envelope = ResetPasswordResourceResponse.model_validate(payload)
        return envelope.data

    async def delete_user(
        self,
        username: str,
        *,
        access_token: str,
        timeout: float | None = None,
    ) -> None:
        """DELETE /auth/users/byUsername/{username}."""
        await self._session.delete_json(
            self._user_path(username),
            timeout=timeout,
            expected_status=(200, 204),
            extra_headers=_bearer_headers(access_token),
        )

    async def delete_user_if_exists(
        self,
        username: str,
        *,
        access_token: str,
        timeout: float | None = None,
    ) -> bool:
        """DELETE when present; return True if a user was removed."""
        try:
            await self.delete_user(username, access_token=access_token, timeout=timeout)
        except RobotApiError as exc:
            if exc.status_code == 404:
                return False
            raise
        return True


def _bearer_headers(access_token: str | None) -> dict[str, str] | None:
    if not access_token:
        return None
    return {"Authorization": f"Bearer {access_token}"}
