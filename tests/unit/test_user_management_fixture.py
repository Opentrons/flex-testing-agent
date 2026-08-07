"""Unit tests for idempotent user-management fixtures."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.clients.users import UsersClient
from flex_testing_agent.fixtures.user_management import (
    EphemeralUserSpec,
    ensure_user_absent,
    ensure_user_present,
    verify_user_missing,
)

_BASE = "http://127.0.0.1:31950"
_USER = {
    "username": "flex_harness_um_crud",
    "fullName": "Flex Harness UM CRUD",
    "accountType": "user",
    "scopes": [],
    "locked": False,
    "resetPassword": False,
}


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_ensure_user_absent_idempotent_on_404() -> None:
    route = respx.delete(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        return_value=httpx.Response(404, text="not found")
    )
    async with RobotHttpSession(_BASE) as session:
        users = UsersClient(session)
        removed = await ensure_user_absent(
            users,
            "flex_harness_um_crud",
            admin_token="admin-tok",
        )
    assert removed is False
    assert route.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_ensure_user_present_deletes_then_creates() -> None:
    delete_route = respx.delete(
        f"{_BASE}/auth/users/byUsername/flex_harness_um_crud"
    ).mock(return_value=httpx.Response(404, text="not found"))
    create_route = respx.post(f"{_BASE}/auth/users").mock(
        return_value=httpx.Response(201, json={"data": _USER})
    )
    spec = EphemeralUserSpec.default()
    async with RobotHttpSession(_BASE) as session:
        users = UsersClient(session)
        await ensure_user_present(users, spec, admin_token="admin-tok")
    assert delete_route.call_count == 1
    assert create_route.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_verify_user_missing_accepts_404() -> None:
    respx.get(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        return_value=httpx.Response(404, text="not found")
    )
    async with RobotHttpSession(_BASE) as session:
        users = UsersClient(session)
        await verify_user_missing(
            users,
            "flex_harness_um_crud",
            admin_token="admin-tok",
        )
