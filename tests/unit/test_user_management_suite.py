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
from flex_testing_agent.fixtures.user_management import (
    EPHEMERAL_USERNAME_RENAMED,
    EPHEMERAL_USERNAME_SELF_TMP,
    EPHEMERAL_USERNAME_TOKEN_REV,
    EPHEMERAL_USERNAME_TOKEN_REV_REN,
)

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
    self_username = {"value": "flex_harness_um_crud"}
    revoked_tokens: set[str] = set()
    tok_rev = {
        "exists": False,
        "username": EPHEMERAL_USERNAME_TOKEN_REV,
        "full_name": "Flex Harness UM Token Rev",
        "account_type": "user",
        "locked": False,
    }

    def _delete_original(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        if auth == "Bearer operator-tok":
            return httpx.Response(403, json={"errors": [{"title": "Forbidden"}]})
        return httpx.Response(404, text="not found")

    def _post_users(request: httpx.Request) -> httpx.Response:
        data = _json_data(request)
        username = str(data.get("username") or "")
        if username == EPHEMERAL_USERNAME_TOKEN_REV:
            tok_rev["exists"] = True
            tok_rev["username"] = EPHEMERAL_USERNAME_TOKEN_REV
            tok_rev["full_name"] = str(data.get("fullName") or tok_rev["full_name"])
            tok_rev["account_type"] = str(data.get("accountType") or "user")
            tok_rev["locked"] = False
            revoked_tokens.discard("rev-tok")
            return httpx.Response(
                201,
                json={
                    "data": _user(
                        username=EPHEMERAL_USERNAME_TOKEN_REV,
                        full_name=str(tok_rev["full_name"]),
                        account_type=str(tok_rev["account_type"]),
                    )
                },
            )
        create_count["n"] += 1
        if create_count["n"] == 1:
            self_username["value"] = "flex_harness_um_crud"
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
        username = form.get("username", "")
        if username == EPHEMERAL_USERNAME_TOKEN_REV and password == "FlexHarnessUm1!":
            return httpx.Response(
                200,
                json={
                    "access_token": "rev-tok",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        if (
            reset_done["value"]
            and not rotated["value"]
            and password == "FlexHarnessUm1!"
            and username == EPHEMERAL_USERNAME_RENAMED
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

    def _patch_self(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        if auth == "Bearer rev-tok":
            if "rev-tok" in revoked_tokens or not tok_rev["exists"]:
                return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
            data = _json_data(request)
            full_name = data.get("fullName")
            return httpx.Response(
                200,
                json={
                    "data": _user(
                        username=str(tok_rev["username"]),
                        full_name=(
                            str(full_name)
                            if full_name is not None
                            else str(tok_rev["full_name"])
                        ),
                        account_type=str(tok_rev["account_type"]),
                    )
                },
            )
        data = _json_data(request)
        if data.get("password"):
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
        if data.get("username") is not None:
            self_username["value"] = str(data["username"])
        full_name = data.get("fullName")
        return httpx.Response(
            200,
            json={
                "data": _user(
                    username=self_username["value"],
                    full_name=(
                        str(full_name)
                        if full_name is not None
                        else "Flex Harness UM CRUD"
                    ),
                )
            },
        )

    def _get_self(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        if auth == "Bearer rev-tok":
            if "rev-tok" in revoked_tokens or not tok_rev["exists"]:
                return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
            return httpx.Response(
                200,
                json={
                    "data": _user(
                        username=str(tok_rev["username"]),
                        full_name=str(tok_rev["full_name"]),
                        account_type=str(tok_rev["account_type"]),
                    )
                },
            )
        return httpx.Response(200, json={"data": _user()})

    def _patch_tok_rev(request: httpx.Request) -> httpx.Response:
        data = _json_data(request)
        if data.get("username") == EPHEMERAL_USERNAME_TOKEN_REV_REN:
            tok_rev["username"] = EPHEMERAL_USERNAME_TOKEN_REV_REN
            revoked_tokens.add("rev-tok")
            return httpx.Response(
                200,
                json={"data": _user(username=EPHEMERAL_USERNAME_TOKEN_REV_REN)},
            )
        if data.get("accountType"):
            tok_rev["account_type"] = str(data["accountType"])
            revoked_tokens.add("rev-tok")
            return httpx.Response(
                200,
                json={"data": _user(account_type=str(tok_rev["account_type"]))},
            )
        if data.get("locked") is True:
            tok_rev["locked"] = True
            revoked_tokens.add("rev-tok")
            payload = _user()
            payload["locked"] = True
            payload["username"] = tok_rev["username"]
            return httpx.Response(200, json={"data": payload})
        if data.get("fullName"):
            tok_rev["full_name"] = str(data["fullName"])
            return httpx.Response(
                200,
                json={"data": _user(full_name=str(tok_rev["full_name"]))},
            )
        return httpx.Response(200, json={"data": _user()})

    def _delete_tok_rev(_request: httpx.Request) -> httpx.Response:
        if not tok_rev["exists"]:
            return httpx.Response(404, text="not found")
        tok_rev["exists"] = False
        revoked_tokens.add("rev-tok")
        return httpx.Response(200, json={"data": None})

    def _reset_tok_rev(_request: httpx.Request) -> httpx.Response:
        revoked_tokens.add("rev-tok")
        return httpx.Response(
            200,
            json={
                "data": {
                    **_user(username=EPHEMERAL_USERNAME_TOKEN_REV, reset_password=True),
                    "temporaryPassword": "TempPass123!",
                }
            },
        )

    renamed_delete_count = {"n": 0}

    def _delete_renamed(_request: httpx.Request) -> httpx.Response:
        renamed_delete_count["n"] += 1
        # First call is setup cleanup (absent); later call is suite teardown.
        if renamed_delete_count["n"] == 1:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, json={"data": None})

    respx.delete(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        side_effect=_delete_original
    )
    respx.delete(f"{_BASE}/auth/users/byUsername/{EPHEMERAL_USERNAME_SELF_TMP}").mock(
        return_value=httpx.Response(404, text="not found")
    )
    respx.delete(f"{_BASE}/auth/users/byUsername/{EPHEMERAL_USERNAME_TOKEN_REV}").mock(
        side_effect=_delete_tok_rev
    )
    respx.delete(
        f"{_BASE}/auth/users/byUsername/{EPHEMERAL_USERNAME_TOKEN_REV_REN}"
    ).mock(return_value=httpx.Response(404, text="not found"))
    respx.delete(f"{_BASE}/auth/users/byUsername/{EPHEMERAL_USERNAME_RENAMED}").mock(
        side_effect=_delete_renamed
    )
    respx.post(f"{_BASE}/auth/users").mock(side_effect=_post_users)
    respx.get(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        return_value=httpx.Response(200, json={"data": _user()})
    )
    respx.get(f"{_BASE}/auth/users/self").mock(side_effect=_get_self)
    respx.patch(f"{_BASE}/auth/users/byUsername/flex_harness_um_crud").mock(
        side_effect=_patch_original
    )
    respx.patch(f"{_BASE}/auth/users/byUsername/{EPHEMERAL_USERNAME_TOKEN_REV}").mock(
        side_effect=_patch_tok_rev
    )
    respx.post(
        f"{_BASE}/auth/users/byUsername/{EPHEMERAL_USERNAME_TOKEN_REV}/resetPassword"
    ).mock(side_effect=_reset_tok_rev)
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
        side_effect=lambda request: httpx.Response(
            200,
            json={
                "active": "rev-tok" not in revoked_tokens,
                "username": (
                    str(tok_rev["username"])
                    if request.content and b"rev-tok" in request.content
                    else EPHEMERAL_USERNAME_RENAMED
                ),
            },
        )
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
        "setup_delete_self_tmp_if_exists",
        "setup_delete_token_rev_if_exists",
        "setup_delete_token_rev_renamed_if_exists",
        "setup_delete_renamed_if_exists",
        "post_create_user",
        "get_by_username",
        "get_self",
        "patch_self_full_name",
        "self_routes_after_username_change",
        "token_revoked_after_admin_edit_username",
        "token_revoked_after_admin_edit_role",
        "token_valid_after_admin_edit_legal_name",
        "token_revoked_after_admin_delete_user",
        "token_revoked_after_admin_lock_account",
        "token_revoked_after_admin_reset_password",
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
