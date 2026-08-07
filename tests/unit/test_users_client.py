"""Unit tests for auth-server UsersClient."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.clients.users import UsersClient
from flex_testing_agent.models.auth_users import UpdateSelfRequest, UpdateUserRequest

_BASE = "http://127.0.0.1:31950"
_USER = {
    "username": "flex_harness_um_crud",
    "fullName": "Flex Harness UM CRUD",
    "accountType": "user",
    "scopes": [],
    "locked": False,
    "resetPassword": False,
}


@pytest.fixture
async def session() -> RobotHttpSession:
    client = RobotHttpSession(_BASE, timeout_seconds=1.0)
    yield client
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_create_user(session: RobotHttpSession) -> None:
    route = respx.post(f"{_BASE}/auth/users").mock(
        return_value=httpx.Response(201, json={"data": _USER})
    )
    client = UsersClient(session)
    profile = await client.create_user(
        username="flex_harness_um_crud",
        password="FlexHarnessUm1!",
        full_name="Flex Harness UM CRUD",
        account_type="user",
        access_token="admin-tok",
    )
    assert profile.user_name == "flex_harness_um_crud"
    assert route.calls[0].request.headers["Authorization"] == "Bearer admin-tok"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_get_user_by_username(session: RobotHttpSession) -> None:
    respx.get(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        return_value=httpx.Response(200, json={"data": _USER})
    )
    client = UsersClient(session)
    profile = await client.get_user_by_username(
        "flex_harness_um_crud",
        access_token="admin-tok",
    )
    assert profile.full_name == "Flex Harness UM CRUD"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_get_self(session: RobotHttpSession) -> None:
    respx.get(f"{_BASE}/auth/users/self").mock(
        return_value=httpx.Response(200, json={"data": _USER})
    )
    client = UsersClient(session)
    profile = await client.get_self(access_token="subject-tok")
    assert profile.account_type == "user"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_update_user(session: RobotHttpSession) -> None:
    route = respx.patch(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        return_value=httpx.Response(
            200,
            json={"data": {**_USER, "fullName": "Updated Name"}},
        )
    )
    client = UsersClient(session)
    profile = await client.update_user(
        "flex_harness_um_crud",
        UpdateUserRequest(full_name="Updated Name"),
        access_token="admin-tok",
    )
    assert profile.full_name == "Updated Name"
    assert route.calls[0].request.headers["Authorization"] == "Bearer admin-tok"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_update_self(session: RobotHttpSession) -> None:
    route = respx.patch(f"{_BASE}/auth/users/self").mock(
        return_value=httpx.Response(
            200,
            json={"data": {**_USER, "resetPassword": False}},
        )
    )
    client = UsersClient(session)
    profile = await client.update_self(
        UpdateSelfRequest(password="FlexHarnessUm2!"),
        access_token="subject-tok",
    )
    assert profile.reset_password is False
    assert route.calls[0].request.headers["Authorization"] == "Bearer subject-tok"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_reset_password(session: RobotHttpSession) -> None:
    respx.post(
        f"{_BASE}/auth/users/byUsername/flex_harness_um_crud/resetPassword"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    **_USER,
                    "resetPassword": True,
                    "temporaryPassword": "TempPass123!",
                }
            },
        )
    )
    client = UsersClient(session)
    profile = await client.reset_password(
        "flex_harness_um_crud",
        access_token="admin-tok",
    )
    assert profile.temporary_password == "TempPass123!"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_delete_user(session: RobotHttpSession) -> None:
    route = respx.delete(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    client = UsersClient(session)
    await client.delete_user("flex_harness_um_crud", access_token="admin-tok")
    assert route.calls[0].request.headers["Authorization"] == "Bearer admin-tok"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_delete_user_if_exists_returns_false_on_404(
    session: RobotHttpSession,
) -> None:
    respx.delete(f"{_BASE}/auth/users/byUsername/missing").mock(
        return_value=httpx.Response(404, text="not found")
    )
    client = UsersClient(session)
    removed = await client.delete_user_if_exists("missing", access_token="admin-tok")
    assert removed is False
