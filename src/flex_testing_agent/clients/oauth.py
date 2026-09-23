"""OAuth2 token client (ROPC) for CRS-on testing.

The harness mints access tokens via resource-owner password credentials only.
It does not perform refresh-token grants. Authenticated API calls do not extend
access-token lifetime; the Opentrons App rotates sessions with refresh tokens.
Long harness runs rely on a high ``idleLogout`` at CRS enable time and on
re-authenticating via ROPC when a token expires.
"""

from __future__ import annotations

from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.models.auth_users import (
    TokenIntrospectionResponse,
    TokenResponse,
)

DEFAULT_OAUTH_CLIENT_ID = "opentrons_app"


class OAuthClient:
    """Atomic client for ``/auth/oauth2/*`` endpoints."""

    def __init__(
        self,
        session: RobotHttpSession,
        *,
        client_id: str = DEFAULT_OAUTH_CLIENT_ID,
    ) -> None:
        self._session = session
        self._client_id = client_id

    async def get_token(
        self,
        username: str,
        password: str,
        *,
        scope: str | None = None,
        timeout: float | None = None,
    ) -> TokenResponse:
        """Resource-owner password credentials grant."""
        form: dict[str, str] = {
            "grant_type": "password",
            "client_id": self._client_id,
            "username": username,
            "password": password,
        }
        if scope is not None:
            form["scope"] = scope
        payload = await self._session.post_form(
            "/auth/oauth2/token",
            form=form,
            timeout=timeout,
        )
        return TokenResponse.model_validate(payload)

    async def refresh_access_token(
        self,
        refresh_token: str,
        *,
        timeout: float | None = None,
    ) -> TokenResponse:
        """Refresh-token grant (Opentrons App session rotation)."""
        form: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
        }
        payload = await self._session.post_form(
            "/auth/oauth2/token",
            form=form,
            timeout=timeout,
        )
        return TokenResponse.model_validate(payload)

    async def introspect_token(
        self,
        token: str,
        *,
        timeout: float | None = None,
    ) -> TokenIntrospectionResponse:
        """RFC 7662 token introspection for an access token."""
        payload = await self._session.post_form(
            "/auth/oauth2/introspect",
            form={"token": token, "client_id": self._client_id},
            timeout=timeout,
        )
        return TokenIntrospectionResponse.model_validate(payload)
