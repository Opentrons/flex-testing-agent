"""Unit tests for OAuth client."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.clients.session import RobotHttpSession


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_oauth_get_token_ropc() -> None:
    respx.post("http://127.0.0.1:31950/auth/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "tok",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "protocols.write",
            },
        ),
    )
    async with RobotHttpSession("http://127.0.0.1:31950") as session:
        client = OAuthClient(session)
        token = await client.get_token("flex_test_admin", "pw")
    assert token.access_token == "tok"
    assert token.token_type == "Bearer"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_oauth_introspect_token() -> None:
    respx.post("http://127.0.0.1:31950/auth/oauth2/introspect").mock(
        return_value=httpx.Response(
            200,
            json={
                "active": True,
                "username": "flex_harness_um_crud",
                "scope": "users.read.self",
                "client_id": "opentrons_app",
            },
        ),
    )
    async with RobotHttpSession("http://127.0.0.1:31950") as session:
        client = OAuthClient(session)
        body = await client.introspect_token("access-tok")
    assert body.active is True
    assert body.username == "flex_harness_um_crud"
