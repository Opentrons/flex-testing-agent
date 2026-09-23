"""Unit tests for auditor onboarding temp-password retest."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.user_management_suite import (
    run_account_type_onboarding_comparison,
    run_auditor_onboarding_retest,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.user_management import (
    DEFAULT_AUDITOR_INITIAL_PASSWORD,
    DEFAULT_AUDITOR_ROTATED_PASSWORD,
    DEFAULT_EPHEMERAL_PASSWORD,
    DEFAULT_EPHEMERAL_PASSWORD_ROTATED,
    EPHEMERAL_USERNAME_AUDITOR,
    EPHEMERAL_USERNAME_USER_ONBOARD,
)

_BASE = "http://127.0.0.1:31950"
_USERNAME = EPHEMERAL_USERNAME_AUDITOR
_TEMP_PASSWORD = "TempAuditor123!"
_TEMP_REFRESH = "temp-refresh"
_NEW_REFRESH = "new-refresh"


def _auditor(*, reset_password: bool = False) -> dict[str, object]:
    return {
        "username": _USERNAME,
        "fullName": "Flex Harness UM Auditor",
        "accountType": "auditor",
        "scopes": ["users.read.others"],
        "locked": False,
        "resetPassword": reset_password,
    }


def _mock_auditor_onboarding_routes(*, new_password_login_fails: bool) -> None:
    rotated = {"value": False}

    respx.delete(f"{_BASE}/auth/users/byUsername/{_USERNAME}").mock(
        return_value=httpx.Response(404, text="not found"),
    )
    respx.post(f"{_BASE}/auth/users").mock(
        return_value=httpx.Response(201, json={"data": _auditor()}),
    )
    respx.post(f"{_BASE}/auth/users/byUsername/{_USERNAME}/resetPassword").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    **_auditor(reset_password=True),
                    "temporaryPassword": _TEMP_PASSWORD,
                }
            },
        ),
    )

    def _get_self(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        reset_password = auth == "Bearer temp-tok"
        return httpx.Response(
            200,
            json={"data": _auditor(reset_password=reset_password)},
        )

    respx.get(f"{_BASE}/auth/users/self").mock(side_effect=_get_self)

    def _patch_self(_request: httpx.Request) -> httpx.Response:
        rotated["value"] = True
        return httpx.Response(200, json={"data": _auditor(reset_password=False)})

    respx.patch(f"{_BASE}/auth/users/self").mock(side_effect=_patch_self)

    def _post_token(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        grant_type = form.get("grant_type", ["password"])[0]
        if grant_type == "refresh_token":
            refresh_token = form.get("refresh_token", [""])[0]
            if refresh_token == _TEMP_REFRESH:
                return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
            if refresh_token == _NEW_REFRESH:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "refreshed-tok",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "refresh_token": "new-refresh-rotated",
                    },
                )
            return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})

        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        if username != _USERNAME:
            return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
        if password == _TEMP_PASSWORD and not rotated["value"]:
            return httpx.Response(
                200,
                json={
                    "access_token": "temp-tok",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "refresh_token": _TEMP_REFRESH,
                },
            )
        if password == DEFAULT_AUDITOR_INITIAL_PASSWORD:
            return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
        if password == _TEMP_PASSWORD and rotated["value"]:
            return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
        if password == DEFAULT_AUDITOR_ROTATED_PASSWORD:
            if new_password_login_fails:
                return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
            return httpx.Response(
                200,
                json={
                    "access_token": "new-tok",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "refresh_token": _NEW_REFRESH,
                },
            )
        return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})

    respx.post(f"{_BASE}/auth/oauth2/token").mock(side_effect=_post_token)
    respx.post(f"{_BASE}/auth/oauth2/introspect").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json={
                "active": parse_qs(request.content.decode()).get("token", [""])[0]
                in {"new-tok", "refreshed-tok"},
                "username": _USERNAME,
                "sub": _USERNAME,
                "scope": "users.read.others",
            },
        ),
    )
    respx.delete(f"{_BASE}/auth/users/byUsername/{_USERNAME}").mock(
        return_value=httpx.Response(204),
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_auditor_onboarding_retest_happy_path(tmp_path: Path) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    _mock_auditor_onboarding_routes(new_password_login_fails=False)

    with patch(
        "flex_testing_agent.capabilities.user_management_suite.access_token_for_username",
        new=AsyncMock(return_value="admin-tok"),
    ):
        result = await run_auditor_onboarding_retest(settings)

    assert result.ok is True
    assert result.account_type == "auditor"
    step_names = [probe.step for probe in result.probes]
    assert "login_new_password" in step_names
    assert "login_new_password_repeat" in step_names
    assert "refresh_temp_password_token_rejected" in step_names
    assert "refresh_new_password_token" in step_names
    assert "get_self_with_new_password_ropc_token" in step_names
    assert "get_self_with_refreshed_token" in step_names


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_auditor_onboarding_retest_detects_new_password_login_failure(
    tmp_path: Path,
) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    _mock_auditor_onboarding_routes(new_password_login_fails=True)

    with patch(
        "flex_testing_agent.capabilities.user_management_suite.access_token_for_username",
        new=AsyncMock(return_value="admin-tok"),
    ):
        result = await run_auditor_onboarding_retest(settings)

    assert result.ok is False
    assert "login_new_password" in result.detail
    assert DEFAULT_AUDITOR_INITIAL_PASSWORD != DEFAULT_AUDITOR_ROTATED_PASSWORD


def _mock_comparison_routes(*, auditor_get_self_status: int) -> None:
    rotated: dict[str, bool] = {"auditor": False, "user": False}

    def _delete(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    def _post_users(request: httpx.Request) -> httpx.Response:
        import json

        data = json.loads(request.content.decode()).get("data", {})
        account_type = str(data.get("accountType") or "user")
        username = str(data.get("username") or "")
        return httpx.Response(
            201,
            json={
                "data": {
                    "username": username,
                    "fullName": str(data.get("fullName") or ""),
                    "accountType": account_type,
                    "scopes": [],
                    "locked": False,
                    "resetPassword": False,
                }
            },
        )

    def _reset(request: httpx.Request) -> httpx.Response:
        username = request.url.path.split("/byUsername/")[1].split("/")[0]
        account_type = "auditor" if username == EPHEMERAL_USERNAME_AUDITOR else "user"
        return httpx.Response(
            200,
            json={
                "data": {
                    "username": username,
                    "fullName": "Test",
                    "accountType": account_type,
                    "scopes": [],
                    "locked": False,
                    "resetPassword": True,
                    "temporaryPassword": _TEMP_PASSWORD,
                }
            },
        )

    def _get_self(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        if auth == "Bearer temp-tok":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "username": _USERNAME,
                        "fullName": "Test",
                        "accountType": "auditor",
                        "scopes": [],
                        "locked": False,
                        "resetPassword": True,
                    }
                },
            )
        if auth == "Bearer user-temp-tok":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "username": EPHEMERAL_USERNAME_USER_ONBOARD,
                        "fullName": "Test",
                        "accountType": "user",
                        "scopes": [],
                        "locked": False,
                        "resetPassword": True,
                    }
                },
            )
        if auth == "Bearer new-tok":
            status = auditor_get_self_status
            username = _USERNAME
            account_type = "auditor"
        elif auth == "Bearer user-new-tok":
            status = 200
            username = EPHEMERAL_USERNAME_USER_ONBOARD
            account_type = "user"
        else:
            return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
        if status != 200:
            return httpx.Response(status, json={"errors": [{"title": "Forbidden"}]})
        return httpx.Response(
            200,
            json={
                "data": {
                    "username": username,
                    "fullName": "Test",
                    "accountType": account_type,
                    "scopes": [],
                    "locked": False,
                    "resetPassword": False,
                }
            },
        )

    def _patch_self(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        if auth == "Bearer temp-tok":
            rotated["auditor"] = True
            username = _USERNAME
            account_type = "auditor"
        elif auth == "Bearer user-temp-tok":
            rotated["user"] = True
            username = EPHEMERAL_USERNAME_USER_ONBOARD
            account_type = "user"
        else:
            return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
        return httpx.Response(
            200,
            json={
                "data": {
                    "username": username,
                    "fullName": "Test",
                    "accountType": account_type,
                    "scopes": [],
                    "locked": False,
                    "resetPassword": False,
                }
            },
        )

    def _post_token(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        grant_type = form.get("grant_type", ["password"])[0]
        if grant_type == "refresh_token":
            return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})

        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        if username == _USERNAME:
            if password == _TEMP_PASSWORD and not rotated["auditor"]:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "temp-tok",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "refresh_token": _TEMP_REFRESH,
                    },
                )
            if password == DEFAULT_AUDITOR_ROTATED_PASSWORD:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "new-tok",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "refresh_token": _NEW_REFRESH,
                    },
                )
        if username == EPHEMERAL_USERNAME_USER_ONBOARD:
            if password == _TEMP_PASSWORD and not rotated["user"]:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "user-temp-tok",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "refresh_token": "user-temp-refresh",
                    },
                )
            if password == DEFAULT_EPHEMERAL_PASSWORD_ROTATED:
                return httpx.Response(
                    200,
                    json={
                        "access_token": "user-new-tok",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "refresh_token": "user-new-refresh",
                    },
                )
            if password == DEFAULT_EPHEMERAL_PASSWORD:
                return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
        if password == DEFAULT_AUDITOR_INITIAL_PASSWORD:
            return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
        if password == _TEMP_PASSWORD:
            return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})
        return httpx.Response(401, json={"errors": [{"title": "Unauthorized"}]})

    for username in (_USERNAME, EPHEMERAL_USERNAME_USER_ONBOARD):
        respx.delete(f"{_BASE}/auth/users/byUsername/{username}").mock(
            side_effect=_delete
        )
        respx.post(f"{_BASE}/auth/users/byUsername/{username}/resetPassword").mock(
            side_effect=_reset,
        )
    respx.post(f"{_BASE}/auth/users").mock(side_effect=_post_users)
    respx.get(f"{_BASE}/auth/users/self").mock(side_effect=_get_self)
    respx.patch(f"{_BASE}/auth/users/self").mock(side_effect=_patch_self)
    respx.post(f"{_BASE}/auth/oauth2/token").mock(side_effect=_post_token)
    respx.post(f"{_BASE}/auth/oauth2/introspect").mock(
        return_value=httpx.Response(
            200,
            json={"active": True, "username": _USERNAME, "sub": _USERNAME},
        ),
    )


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_account_type_onboarding_comparison_flags_auditor_specific(
    tmp_path: Path,
) -> None:
    settings = Settings(
        robot_host="127.0.0.1",
        robot_http_port=31950,
        allow_mutations=True,
        artifact_directory=tmp_path / "artifacts",
    )
    _mock_comparison_routes(auditor_get_self_status=403)

    with patch(
        "flex_testing_agent.capabilities.user_management_suite.access_token_for_username",
        new=AsyncMock(return_value="admin-tok"),
    ):
        comparison = await run_account_type_onboarding_comparison(settings)

    assert comparison.auditor_specific is True
    by_type = {item.account_type: item for item in comparison.results}
    assert by_type["auditor"].post_rotation_get_self_status == 403
    assert by_type["user"].post_rotation_get_self_status == 200
