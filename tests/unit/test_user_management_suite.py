"""Unit tests for CRS-on user-management suite."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

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
    account_type: str = "user",
    reset_password: bool = False,
) -> dict[str, object]:
    return {
        "username": username,
        "fullName": full_name,
        "accountType": account_type,
        "scopes": [],
        "locked": False,
        "resetPassword": reset_password,
    }


def _json_data(request: httpx.Request) -> dict[str, object]:
    if not request.content:
        return {}
    payload = json.loads(request.content.decode())
    data = payload.get("data", payload)
    return data if isinstance(data, dict) else {}


def _mock_user_management_routes() -> None:
    create_count = {"n": 0}
    reset_done = {"value": False}
    rotated = {"value": False}

    def _delete_original(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        if auth == "Bearer operator-tok":
            return httpx.Response(403, json={"errors": [{"title": "Forbidden"}]})
        return httpx.Response(404, text="not found")

    def _post_users(request: httpx.Request) -> httpx.Response:
        create_count["n"] += 1
        if create_count["n"] == 1:
            return httpx.Response(201, json={"data": _user()})
        return httpx.Response(422, json={"errors": [{"title": "User exists"}]})

    def _patch_original(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        if auth == "Bearer operator-tok":
            return httpx.Response(403, json={"errors": [{"title": "Forbidden"}]})
        data = _json_data(request)
        if data.get("accountType") == "auditor":
            return httpx.Response(200, json={"data": _user(account_type="auditor")})
        if data.get("accountType") == "user":
            return httpx.Response(200, json={"data": _user()})
        if data.get("username") == EPHEMERAL_USERNAME_RENAMED:
            return httpx.Response(
                200,
                json={"data": _user(username=EPHEMERAL_USERNAME_RENAMED)},
            )
        if data.get("fullName"):
            return httpx.Response(
                200,
                json={"data": _user(full_name=str(data["fullName"]))},
            )
        return httpx.Response(200, json={"data": _user()})

    def _oauth_token(request: httpx.Request) -> httpx.Response:
        form = {
            key: values[0] for key, values in parse_qs(request.content.decode()).items()
        }
        password = form.get("password", "")
        if (
            reset_done["value"]
            and not rotated["value"]
            and password == "FlexHarnessUm1!"
        ):
            return httpx.Response(400, json={"error": "invalid_grant"})
        if rotated["value"] and password == "TempPass123!":
            return httpx.Response(400, json={"error": "invalid_grant"})
        if password in {"FlexHarnessUm1!", "TempPass123!", "FlexHarnessUm2!"}:
            return httpx.Response(
                200,
                json={
                    "access_token": "subject-tok",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(400, json={"error": "invalid_grant"})

    def _reset_password(_request: httpx.Request) -> httpx.Response:
        reset_done["value"] = True
        return httpx.Response(
            200,
            json={
                "data": {
                    **_user(username=EPHEMERAL_USERNAME_RENAMED, reset_password=True),
                    "temporaryPassword": "TempPass123!",
                }
            },
        )

    def _patch_self(_request: httpx.Request) -> httpx.Response:
        rotated["value"] = True
        return httpx.Response(
            200,
            json={
                "data": _user(
                    username=EPHEMERAL_USERNAME_RENAMED,
                    reset_password=False,
                )
            },
        )

    respx.delete(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        side_effect=_delete_original
    )
    respx.post(f"{_BASE}/auth/users").mock(side_effect=_post_users)
    respx.get(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        return_value=httpx.Response(200, json={"data": _user()})
    )
    respx.get(f"{_BASE}/auth/users/self").mock(
        return_value=httpx.Response(200, json={"data": _user()})
    )
    respx.patch(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        side_effect=_patch_original
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
    ).mock(side_effect=_reset_password)
    respx.patch(f"{_BASE}/auth/users/self").mock(side_effect=_patch_self)
    respx.post(f"{_BASE}/auth/oauth2/token").mock(side_effect=_oauth_token)
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

    async def _tokens(settings: Settings, username: str) -> str:
        if username == "flex_test_operator":
            return "operator-tok"
        return "admin-tok"

    with patch(
        "flex_testing_agent.capabilities.user_management_suite.access_token_for_username",
        new=AsyncMock(side_effect=_tokens),
    ):
        result = await run_user_management_suite(settings)

    assert result.fail_count == 0, [s.model_dump() for s in result.steps if not s.ok]
    step_names = [step.name for step in result.steps]
    assert step_names == [
        "setup_delete_if_exists",
        "post_create_user",
        "get_by_username",
        "get_self",
        "post_duplicate_username_rejected",
        "patch_account_type",
        "operator_patch_forbidden",
        "operator_delete_forbidden",
        "patch_by_username_profile",
        "patch_by_username_rename",
        "patch_by_username_reset_flag",
        "post_reset_password",
        "original_password_rejected_after_reset",
        "patch_self_password",
        "temp_password_rejected_after_rotation",
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
