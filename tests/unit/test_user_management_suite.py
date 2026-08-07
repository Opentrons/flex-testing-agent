"""Unit tests for CRS-on user-management suite."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.user_management_suite import (
    run_user_management_suite,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.user_management import EPHEMERAL_USERNAME_RENAMED

_BASE = "http://127.0.0.1:31950"


def _user(
    *,
    username: str = "flex_harness_um_crud",
    full_name: str = "Flex Harness UM CRUD",
    reset_password: bool = False,
) -> dict[str, object]:
    return {
        "username": username,
        "fullName": full_name,
        "accountType": "user",
        "scopes": [],
        "locked": False,
        "resetPassword": reset_password,
    }


def _mock_user_management_routes() -> None:
    respx.delete(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        return_value=httpx.Response(404, text="not found")
    )
    respx.post(f"{_BASE}/auth/users").mock(
        return_value=httpx.Response(201, json={"data": _user()})
    )
    respx.get(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        return_value=httpx.Response(200, json={"data": _user()})
    )
    respx.get(f"{_BASE}/auth/users/self").mock(
        return_value=httpx.Response(200, json={"data": _user()})
    )
    respx.patch(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        side_effect=[
            httpx.Response(
                200,
                json={"data": _user(full_name="Flex Harness UM CRUD Updated")},
            ),
            httpx.Response(
                200,
                json={"data": _user(username=EPHEMERAL_USERNAME_RENAMED)},
            ),
        ]
    )
    respx.patch(f"{_BASE}/auth/users/byUsername/{EPHEMERAL_USERNAME_RENAMED}").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": _user(
                    username=EPHEMERAL_USERNAME_RENAMED,
                    reset_password=True,
                )
            },
        )
    )
    respx.post(
        f"{_BASE}/auth/users/byUsername/{EPHEMERAL_USERNAME_RENAMED}/resetPassword"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    **_user(username=EPHEMERAL_USERNAME_RENAMED, reset_password=True),
                    "temporaryPassword": "TempPass123!",
                }
            },
        )
    )
    respx.patch(f"{_BASE}/auth/users/self").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": _user(
                    username=EPHEMERAL_USERNAME_RENAMED,
                    reset_password=False,
                )
            },
        )
    )
    respx.post(f"{_BASE}/auth/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "subject-tok",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        ),
    )
    respx.post(f"{_BASE}/auth/oauth2/introspect").mock(
        return_value=httpx.Response(
            200,
            json={"active": True, "username": EPHEMERAL_USERNAME_RENAMED},
        )
    )
    respx.delete(f"{_BASE}/auth/users/byUsername/{EPHEMERAL_USERNAME_RENAMED}").mock(
        return_value=httpx.Response(200, json={"data": None})
    )
    respx.get(f"{_BASE}/auth/users/byUsername/{EPHEMERAL_USERNAME_RENAMED}").mock(
        return_value=httpx.Response(404, text="not found")
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_user_management_suite_happy_path(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    _mock_user_management_routes()

    with patch(
        "flex_testing_agent.capabilities.user_management_suite.access_token_for_username",
        new=AsyncMock(return_value="admin-tok"),
    ):
        result = await run_user_management_suite(settings)

    assert result.fail_count == 0
    step_names = [step.name for step in result.steps]
    assert step_names == [
        "setup_delete_if_exists",
        "post_create_user",
        "get_by_username",
        "get_self",
        "patch_by_username_profile",
        "patch_by_username_rename",
        "patch_by_username_reset_flag",
        "post_reset_password",
        "patch_self_password",
        "get_self_after_password_change",
        "post_oauth2_introspect",
        "delete_user",
        "verify_deleted",
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_user_management_suite_blocked_without_mutations(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        allow_mutations=False,
        artifact_directory=tmp_path / "artifacts",
    )
    from flex_testing_agent.orchestration.gates import MutationDeniedError

    with pytest.raises(MutationDeniedError):
        await run_user_management_suite(settings)
