#!/usr/bin/env python3
"""Validate RQA-6010 / RQA-6011 loosen behavior for empty vs explicit OAuth scope.

Harness baseline: ``OAuthClient.get_token`` omits the ``scope`` form field unless
passed (ROPC: grant_type=password, client_id, username, password only).

This script re-runs the loosen repro both ways:
  - mint_mode=omit: no ``scope`` field (harness / agent default)
  - mint_mode=explicit: request the gated write scopes at mint time

Tickets:
  - RQA-6010: requireAdminCredsForSignoffProtocol → run_signoff.write
  - RQA-6011: requireAdminCredsWhenSendingProtocolToRobot → protocols.write
               requireAdminCredsWhenUpdatingRobotSoftware → updates.write
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.capabilities.crs_on import run_provision_users
from flex_testing_agent.capabilities.fixture_preflight import (
    FixturePreflightResult,
    access_token_for_fixture_user,
    run_fixture_preflight,
)
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.fixtures.auth_settings_suite import default_smoke_protocol_path
from flex_testing_agent.fixtures.crs_users import (
    load_crs_user_fixtures,
    resolve_user_password,
    resolve_user_password_pair,
)
from flex_testing_agent.models.auth_settings import AuthSettingsData
from flex_testing_agent.models.auth_users import UpdateUserRequest
from flex_testing_agent.orchestration.discover import settings_with_resolved_host
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    ensure_run_state,
    release_current_run,
)
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session

ADMIN = "flex_test_admin"
OPERATOR = "flex_test_operator"
SMOKE = default_smoke_protocol_path()
DEFAULT_ART = Path("artifacts/retest-rqa6010-6011-scope-mint")
ART = DEFAULT_ART

GATED_SIGNOFF = "run_signoff.write"
GATED_PROTO_UPDATE = "protocols.write updates.write"


@dataclass
class CaseResult:
    ticket: str
    mint_mode: str
    session_path: str
    flag: str
    scope: str
    token_scope: str | None
    introspect_scopes: list[str]
    introspect_has_scope: bool
    http_status: int | None
    verdict: str
    detail: str


results: list[CaseResult] = []
PREFLIGHT: FixturePreflightResult | None = None


def classify_loosen(
    *,
    has_scope: bool,
    http_status: int | None,
    scope_name: str,
) -> tuple[str, bool]:
    """Return (verdict, is_regression) for post-loosen same-token checks."""
    if has_scope and http_status == 200:
        return "FIXED", False
    if has_scope and http_status != 200:
        return "PARTIAL_SCOPE_ONLY", True
    if not has_scope and http_status == 200:
        return "PARTIAL_HTTP_ONLY", True
    if http_status == 403:
        return "STILL_OPEN", True
    return f"UNEXPECTED_HTTP_{http_status}", True


def print_case(case: CaseResult) -> None:
    results.append(case)
    print(
        f"[{case.verdict}] {case.ticket} mint={case.mint_mode} "
        f"path={case.session_path} {case.flag} → {case.scope}: {case.detail}"
    )


async def fresh_admin_token(settings) -> str:
    if PREFLIGHT is not None:
        return await access_token_for_fixture_user(
            settings,
            ADMIN,
            inspection=PREFLIGHT.inspection_for(ADMIN),
        )
    return await access_token_for_username(
        settings,
        ADMIN,
        allow_admin_recovery=False,
        repair_reset_password=False,
    )


async def unlock_fixture_users(settings) -> list[str]:
    """Unlock all enabled non-recovery fixture users; return usernames unlocked."""
    fixtures = load_crs_user_fixtures()
    admin_token = await fresh_admin_token(settings)
    unlocked: list[str] = []
    async with FlexRobot(settings, access_token=admin_token) as admin:
        for fixture in fixtures.enabled_users():
            if fixture.recovery_only:
                continue
            try:
                profile = await admin.users.get_user_by_username(
                    fixture.username,
                    access_token=admin_token,
                )
            except RobotApiError:
                continue
            if not profile.locked:
                continue
            await admin.users.update_user(
                fixture.username,
                UpdateUserRequest(locked=False),
                access_token=admin_token,
            )
            unlocked.append(fixture.username)
            print(f"INFO: unlocked {fixture.username}")
    return unlocked


async def prepare_fixture_users(settings, *, replace: bool) -> None:
    """Ensure CRS fixture users exist, are unlocked, and can mint tokens."""
    async with FlexRobot(settings) as robot:
        result = await run_provision_users(robot, replace=replace)
    print(
        f"INFO: provision-users ok={result.ok_count} failed={result.fail_count} "
        f"replace={replace}"
    )
    if result.fail_count:
        for outcome in result.outcomes:
            if not outcome.ok:
                print(f"WARN: provision {outcome.username}: {outcome.detail}")
    unlocked = await unlock_fixture_users(settings)
    if unlocked:
        print(f"INFO: unlocked after provision: {', '.join(unlocked)}")
    for username in (ADMIN, OPERATOR):
        await access_token_for_username(settings, username)
        print(f"INFO: verified ROPC login for {username}")


def print_fixture_preflight(preflight: FixturePreflightResult) -> None:
    auth = preflight.auth_settings
    print(
        "PREFLIGHT auth settings: "
        f"protocol={auth.require_admin_creds_when_sending_protocol_to_robot} "
        f"update={auth.require_admin_creds_when_updating_robot_software} "
        f"signoff={auth.require_admin_creds_for_signoff_protocol}"
    )
    for user in preflight.users:
        print(
            f"PREFLIGHT {user.username}: exists={user.exists} "
            f"locked={user.locked} resetPassword={user.reset_password} "
            f"primary={user.primary_probe} alternate={user.alternate_probe} "
            f"working={user.working_credential or 'none'}"
        )
    if preflight.repairs_performed:
        print("PREFLIGHT repairs:", "; ".join(preflight.repairs_performed))
    print(f"PREFLIGHT: {preflight.detail}")


async def restore_settings(
    settings,
    baseline: AuthSettingsData,
    *,
    label: str,
) -> None:
    """Best-effort baseline restore with one admin re-login retry."""
    for attempt in (1, 2):
        token = await fresh_admin_token(settings)
        try:
            async with FlexRobot(settings, access_token=token) as admin:
                await admin.auth_settings.patch_settings(baseline.patch_fields())
            return
        except RobotApiError as exc:
            if attempt == 1 and exc.status_code == 401:
                continue
            print(f"WARN: restore {label} failed: HTTP {exc.status_code}")
            return


def _operator_passwords(settings) -> tuple[str, ...]:
    try:
        primary, alternate = resolve_user_password_pair(OPERATOR, settings=settings)
        return (primary, alternate)
    except ValueError:
        password = resolve_user_password(OPERATOR, settings=settings)
        if not password:
            raise RuntimeError(f"no password for {OPERATOR}") from None
        return (password,)


async def ropc_mint(
    settings,
    *,
    scope: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (access_token, token_response_scope, refresh_token, mint_error)."""
    last_err: str | None = None
    for password in _operator_passwords(settings):
        async with build_robot_http_session(settings) as session:
            try:
                token = await OAuthClient(session).get_token(
                    OPERATOR,
                    password,
                    scope=scope,
                )
            except RobotApiError as exc:
                last_err = f"HTTP {exc.status_code}: {(exc.body or '')[:300]}"
                if exc.status_code in {400, 401}:
                    continue
                return None, None, None, last_err
            else:
                return (
                    token.access_token,
                    (token.scope or None),
                    token.refresh_token,
                    None,
                )
    return None, None, None, last_err


async def refresh_operator_access(
    settings,
    refresh_token: str,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (access_token, token_response_scope, new_refresh_token, error)."""
    async with build_robot_http_session(settings) as session:
        try:
            token = await OAuthClient(session).refresh_access_token(refresh_token)
        except RobotApiError as exc:
            return None, None, None, f"HTTP {exc.status_code}: {(exc.body or '')[:300]}"
        return (
            token.access_token,
            (token.scope or None),
            token.refresh_token,
            None,
        )


async def discover_tightened_omit_scope(settings) -> tuple[str | None, str | None]:
    """Scope string from omit mint while requireAdminCreds* flags are tightened."""
    _token, scope, _refresh, err = await ropc_mint(settings, scope=None)
    return scope, err


async def mint_operator_for_case(
    settings,
    *,
    mint_mode: str,
    allowed_scope: str | None,
    gated_extra: str,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Return (access, token_scope, refresh_token, mint_error, allowed_scope_used)."""
    if mint_mode == "omit":
        access, scope, refresh, err = await ropc_mint(settings, scope=None)
        return access, scope, refresh, err, scope
    if allowed_scope is None:
        allowed_scope, discover_err = await discover_tightened_omit_scope(settings)
        if discover_err or not allowed_scope:
            return None, None, None, discover_err or "empty omit scope", None
    if mint_mode == "explicit_allowed":
        access, scope, refresh, err = await ropc_mint(settings, scope=allowed_scope)
        return access, scope, refresh, err, allowed_scope
    if mint_mode == "explicit_with_gated":
        explicit = f"{allowed_scope} {gated_extra}".strip()
        access, scope, refresh, err = await ropc_mint(settings, scope=explicit)
        return access, scope, refresh, err, allowed_scope
    msg = f"unknown mint_mode: {mint_mode}"
    raise ValueError(msg)


async def introspect_scopes(robot: FlexRobot, token: str) -> list[str]:
    intro = await robot.oauth.introspect_token(token)
    if not intro.scope:
        return []
    return intro.scope.split()


async def try_call(coro) -> tuple[int | None, str]:
    try:
        await coro()
        return 200, "ok"
    except RobotApiError as exc:
        return exc.status_code, (exc.body or "")[:200]


async def resolve_protocol_id(robot: FlexRobot) -> str:
    main_name = SMOKE.name
    for summary in await robot.protocols.list_protocol_summaries():
        files = summary.get("files")
        if not isinstance(files, list):
            continue
        if any(
            isinstance(item, dict)
            and item.get("name") == main_name
            and item.get("role") == "main"
            for item in files
        ):
            pid = summary.get("id")
            if pid:
                return str(pid)
    uploaded = await robot.protocols.upload_protocol(SMOKE)
    data = uploaded.get("data") if isinstance(uploaded, dict) else None
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    raise RuntimeError("could not resolve smoke protocol id")


async def run_6010(settings, *, mint_mode: str) -> None:
    admin_token = await fresh_admin_token(settings)
    async with FlexRobot(settings, access_token=admin_token) as admin:
        baseline = await admin.auth_settings.get_settings()
        run_ids: list[str] = []
        try:
            await ensure_run_state(
                admin,
                DesiredRunState.NO_CURRENT,
                ensure=True,
                capability_name="retest_rqa6010_6011",
                signed_by="Flex Harness Retest",
            )
            await admin.auth_settings.patch_settings(
                {"requireAdminCredsForSignoffProtocol": True},
            )
            tightened = await admin.auth_settings.get_settings()
            (
                op_token,
                token_scope,
                op_refresh,
                mint_err,
                allowed_used,
            ) = await mint_operator_for_case(
                settings,
                mint_mode=mint_mode,
                allowed_scope=None,
                gated_extra=GATED_SIGNOFF,
            )
            if mint_err or not op_token:
                invalid = mint_mode == "explicit_with_gated" and "invalid_scope" in (
                    mint_err or ""
                )
                print_case(
                    CaseResult(
                        ticket="RQA-6010",
                        mint_mode=mint_mode,
                        session_path="mint",
                        flag="requireAdminCredsForSignoffProtocol",
                        scope="run_signoff.write",
                        token_scope=None,
                        introspect_scopes=[],
                        introspect_has_scope=False,
                        http_status=None,
                        verdict="INVALID_SCOPE_OK" if invalid else "MINT_FAIL",
                        detail=(
                            f"mint under tightened flag: {mint_err}; "
                            f"allowed_scope={allowed_used!r}"
                        ),
                    )
                )
                return
            await admin.auth_settings.patch_settings(
                {"requireAdminCredsForSignoffProtocol": False},
            )
            loosened = await admin.auth_settings.get_settings()
            protocol_id = await resolve_protocol_id(admin)

            async def verify_signoff(
                *,
                session_path: str,
                access_token: str,
                response_scope: str | None,
            ) -> None:
                intro_scopes = await introspect_scopes(admin, access_token)
                has = GATED_SIGNOFF in intro_scopes
                created = await admin.runs.create_run(protocol_id=protocol_id)
                run_id = str(created["data"]["id"])
                run_ids.append(run_id)
                if (created["data"].get("status") or "").lower() == "idle":
                    await admin.runs.stop(run_id)
                async with FlexRobot(settings, access_token=access_token) as op:
                    sc, bd = await try_call(
                        lambda: op.runs.sign_off(
                            run_id,
                            signed_by="Operator Loosen Retest",
                        ),
                    )
                verdict, _ = classify_loosen(
                    has_scope=has,
                    http_status=sc,
                    scope_name="run_signoff.write",
                )
                print_case(
                    CaseResult(
                        ticket="RQA-6010",
                        mint_mode=mint_mode,
                        session_path=session_path,
                        flag="requireAdminCredsForSignoffProtocol",
                        scope="run_signoff.write",
                        token_scope=response_scope,
                        introspect_scopes=intro_scopes,
                        introspect_has_scope=has,
                        http_status=sc,
                        verdict=verdict,
                        detail=(
                            "tightened signoff="
                            f"{tightened.require_admin_creds_for_signoff_protocol} "
                            "loosened signoff="
                            f"{loosened.require_admin_creds_for_signoff_protocol}; "
                            f"token.scope={response_scope!r}; "
                            f"introspect={intro_scopes}; signoff HTTP {sc}; "
                            f"body={bd[:100]!r}"
                        ),
                    )
                )
                with contextlib.suppress(Exception):
                    await admin.runs.sign_off(run_id, signed_by="Flex Harness Admin")
                    await admin.runs.set_current(run_id, current=False)

            await verify_signoff(
                session_path="cached_access",
                access_token=op_token,
                response_scope=token_scope,
            )
            await ensure_run_state(
                admin,
                DesiredRunState.NO_CURRENT,
                ensure=True,
                capability_name="retest_rqa6010_6011_refresh",
                signed_by="Flex Harness Retest",
            )
            if not op_refresh:
                print_case(
                    CaseResult(
                        ticket="RQA-6010",
                        mint_mode=mint_mode,
                        session_path="refresh_token",
                        flag="requireAdminCredsForSignoffProtocol",
                        scope="run_signoff.write",
                        token_scope=None,
                        introspect_scopes=[],
                        introspect_has_scope=False,
                        http_status=None,
                        verdict="REFRESH_UNAVAILABLE",
                        detail="ROPC response omitted refresh_token",
                    )
                )
            else:
                (
                    refreshed,
                    ref_scope,
                    _new_refresh,
                    ref_err,
                ) = await refresh_operator_access(
                    settings,
                    op_refresh,
                )
                if ref_err or not refreshed:
                    print_case(
                        CaseResult(
                            ticket="RQA-6010",
                            mint_mode=mint_mode,
                            session_path="refresh_token",
                            flag="requireAdminCredsForSignoffProtocol",
                            scope="run_signoff.write",
                            token_scope=None,
                            introspect_scopes=[],
                            introspect_has_scope=False,
                            http_status=None,
                            verdict="REFRESH_FAIL",
                            detail=f"refresh grant failed: {ref_err}",
                        )
                    )
                else:
                    await verify_signoff(
                        session_path="refresh_token",
                        access_token=refreshed,
                        response_scope=ref_scope,
                    )
        finally:
            for rid in run_ids:
                with contextlib.suppress(Exception):
                    await release_current_run(
                        admin,
                        rid,
                        signed_by="Flex Harness Cleanup",
                    )
            await restore_settings(settings, baseline, label="RQA-6010")


async def _record_6011_scope_results(
    *,
    mint_mode: str,
    session_path: str,
    token_scope: str | None,
    intro_scopes: list[str],
    sc_proto: int,
    bd_proto: str,
    sc_upd: int,
    bd_upd: str,
) -> None:
    for flag, scope, has, sc, bd, expected_ok in (
        (
            "requireAdminCredsWhenSendingProtocolToRobot",
            "protocols.write",
            "protocols.write" in intro_scopes,
            sc_proto,
            bd_proto,
            201,
        ),
        (
            "requireAdminCredsWhenUpdatingRobotSoftware",
            "updates.write",
            "updates.write" in intro_scopes,
            sc_upd,
            bd_upd,
            200,
        ),
    ):
        if sc == expected_ok and has:
            verdict = "FIXED"
        elif sc == 403 and not has:
            verdict = "STILL_OPEN"
        elif has and sc != expected_ok:
            verdict = "PARTIAL_SCOPE_ONLY"
        elif not has and sc == expected_ok:
            verdict = "PARTIAL_HTTP_ONLY"
        else:
            verdict = f"UNEXPECTED_HTTP_{sc}"
        print_case(
            CaseResult(
                ticket="RQA-6011",
                mint_mode=mint_mode,
                session_path=session_path,
                flag=flag,
                scope=scope,
                token_scope=token_scope,
                introspect_scopes=intro_scopes,
                introspect_has_scope=has,
                http_status=sc,
                verdict=verdict,
                detail=(
                    f"token.scope={token_scope!r}; introspect={intro_scopes}; "
                    f"HTTP {sc}; body={bd!r}"
                ),
            )
        )


async def run_6011(settings, *, mint_mode: str) -> None:
    admin_token = await fresh_admin_token(settings)
    async with FlexRobot(settings, access_token=admin_token) as admin:
        baseline = await admin.auth_settings.get_settings()
        try:
            await admin.auth_settings.patch_settings(
                {
                    "requireAdminCredsWhenSendingProtocolToRobot": True,
                    "requireAdminCredsWhenUpdatingRobotSoftware": True,
                },
            )
            (
                op_token,
                token_scope,
                op_refresh,
                mint_err,
                allowed_used,
            ) = await mint_operator_for_case(
                settings,
                mint_mode=mint_mode,
                allowed_scope=None,
                gated_extra=GATED_PROTO_UPDATE,
            )
            if mint_err or not op_token:
                note = (
                    f"mint under tightened flags: {mint_err}; "
                    f"allowed_scope={allowed_used!r}"
                )
                invalid = mint_mode == "explicit_with_gated" and "invalid_scope" in (
                    mint_err or ""
                )
                verdict = "INVALID_SCOPE_OK" if invalid else "MINT_FAIL"
                for flag, scope in (
                    (
                        "requireAdminCredsWhenSendingProtocolToRobot",
                        "protocols.write",
                    ),
                    (
                        "requireAdminCredsWhenUpdatingRobotSoftware",
                        "updates.write",
                    ),
                ):
                    print_case(
                        CaseResult(
                            ticket="RQA-6011",
                            mint_mode=mint_mode,
                            session_path="mint",
                            flag=flag,
                            scope=scope,
                            token_scope=None,
                            introspect_scopes=[],
                            introspect_has_scope=False,
                            http_status=None,
                            verdict=verdict,
                            detail=note,
                        )
                    )
                return
            await admin.auth_settings.patch_settings(
                {
                    "requireAdminCredsWhenSendingProtocolToRobot": False,
                    "requireAdminCredsWhenUpdatingRobotSoftware": False,
                },
            )

            async def verify_proto_update(
                *,
                session_path: str,
                access_token: str,
                response_scope: str | None,
            ) -> None:
                intro_scopes = await introspect_scopes(admin, access_token)
                async with FlexRobot(settings, access_token=access_token) as op:
                    try:
                        uploaded = await op.protocols.upload_protocol(SMOKE)
                        sc_proto = 201
                        pid = (uploaded.get("data") or {}).get("id")
                        if pid:
                            with contextlib.suppress(RobotApiError):
                                await admin.protocols.delete_protocol(str(pid))
                        bd_proto = "ok"
                    except RobotApiError as exc:
                        sc_proto = exc.status_code or 0
                        bd_proto = (exc.body or "")[:100]
                    sc_upd, bd_upd = await try_call(lambda: op.update.begin())
                if sc_upd == 200:
                    with contextlib.suppress(RobotApiError):
                        await admin.update.cancel()
                await _record_6011_scope_results(
                    mint_mode=mint_mode,
                    session_path=session_path,
                    token_scope=response_scope,
                    intro_scopes=intro_scopes,
                    sc_proto=sc_proto,
                    bd_proto=bd_proto,
                    sc_upd=sc_upd,
                    bd_upd=bd_upd,
                )

            await verify_proto_update(
                session_path="cached_access",
                access_token=op_token,
                response_scope=token_scope,
            )
            if not op_refresh:
                for flag, scope in (
                    (
                        "requireAdminCredsWhenSendingProtocolToRobot",
                        "protocols.write",
                    ),
                    (
                        "requireAdminCredsWhenUpdatingRobotSoftware",
                        "updates.write",
                    ),
                ):
                    print_case(
                        CaseResult(
                            ticket="RQA-6011",
                            mint_mode=mint_mode,
                            session_path="refresh_token",
                            flag=flag,
                            scope=scope,
                            token_scope=None,
                            introspect_scopes=[],
                            introspect_has_scope=False,
                            http_status=None,
                            verdict="REFRESH_UNAVAILABLE",
                            detail="ROPC response omitted refresh_token",
                        )
                    )
            else:
                (
                    refreshed,
                    ref_scope,
                    _new_refresh,
                    ref_err,
                ) = await refresh_operator_access(
                    settings,
                    op_refresh,
                )
                if ref_err or not refreshed:
                    for flag, scope in (
                        (
                            "requireAdminCredsWhenSendingProtocolToRobot",
                            "protocols.write",
                        ),
                        (
                            "requireAdminCredsWhenUpdatingRobotSoftware",
                            "updates.write",
                        ),
                    ):
                        print_case(
                            CaseResult(
                                ticket="RQA-6011",
                                mint_mode=mint_mode,
                                session_path="refresh_token",
                                flag=flag,
                                scope=scope,
                                token_scope=None,
                                introspect_scopes=[],
                                introspect_has_scope=False,
                                http_status=None,
                                verdict="REFRESH_FAIL",
                                detail=f"refresh grant failed: {ref_err}",
                            )
                        )
                else:
                    await verify_proto_update(
                        session_path="refresh_token",
                        access_token=refreshed,
                        response_scope=ref_scope,
                    )
        finally:
            await restore_settings(settings, baseline, label="RQA-6011")


async def remint_controls(settings) -> None:
    """After flags are loose, fresh omit + explicit-with-gated mints should work."""
    admin_token = await fresh_admin_token(settings)
    async with FlexRobot(settings, access_token=admin_token) as admin:
        baseline = await admin.auth_settings.get_settings()
        try:
            await admin.auth_settings.patch_settings(
                {
                    "requireAdminCredsForSignoffProtocol": False,
                    "requireAdminCredsWhenSendingProtocolToRobot": False,
                    "requireAdminCredsWhenUpdatingRobotSoftware": False,
                },
            )
            await asyncio.sleep(0.5)
            allowed_scope, discover_err = await discover_tightened_omit_scope(settings)
            if discover_err or not allowed_scope:
                print_case(
                    CaseResult(
                        ticket="CONTROL",
                        mint_mode="discover",
                        session_path="remint",
                        flag="all_requireAdminCreds_false",
                        scope="run_signoff.write+protocols.write+updates.write",
                        token_scope=None,
                        introspect_scopes=[],
                        introspect_has_scope=False,
                        http_status=None,
                        verdict="CONTROL_FAIL",
                        detail=f"could not discover omit scope: {discover_err}",
                    )
                )
                return
            explicit_gated = (
                f"{allowed_scope} {GATED_SIGNOFF} {GATED_PROTO_UPDATE}".strip()
            )
            for mint_mode in ("omit", "explicit_with_gated"):
                if mint_mode == "omit":
                    token, token_scope, _refresh, mint_err = await ropc_mint(
                        settings,
                        scope=None,
                    )
                else:
                    token, token_scope, _refresh, mint_err = await ropc_mint(
                        settings,
                        scope=explicit_gated,
                    )
                if mint_err or not token:
                    print_case(
                        CaseResult(
                            ticket="CONTROL",
                            mint_mode=mint_mode,
                            session_path="remint",
                            flag="all_requireAdminCreds_false",
                            scope="run_signoff.write+protocols.write+updates.write",
                            token_scope=None,
                            introspect_scopes=[],
                            introspect_has_scope=False,
                            http_status=None,
                            verdict="CONTROL_FAIL",
                            detail=f"remint after loosen failed: {mint_err}",
                        )
                    )
                    continue
                intro_scopes = await introspect_scopes(admin, token)
                has_sign = "run_signoff.write" in intro_scopes
                has_proto = "protocols.write" in intro_scopes
                has_upd = "updates.write" in intro_scopes
                ok = has_sign and has_proto and has_upd
                print_case(
                    CaseResult(
                        ticket="CONTROL",
                        mint_mode=mint_mode,
                        session_path="remint",
                        flag="all_requireAdminCreds_false",
                        scope="run_signoff.write+protocols.write+updates.write",
                        token_scope=token_scope,
                        introspect_scopes=intro_scopes,
                        introspect_has_scope=ok,
                        http_status=200 if ok else None,
                        verdict="CONTROL_OK" if ok else "CONTROL_FAIL",
                        detail=(
                            f"token.scope={token_scope!r}; signoff={has_sign} "
                            f"protocols={has_proto} updates={has_upd}"
                        ),
                    )
                )
        finally:
            await restore_settings(settings, baseline, label="CONTROL")


def write_report(settings, *, robot_version: str | None) -> None:
    out_json = ART / "results.json"
    out_json.write_text(
        json.dumps([asdict(r) for r in results], indent=2) + "\n",
        encoding="utf-8",
    )

    loosen_cases = [
        r
        for r in results
        if r.ticket in ("RQA-6010", "RQA-6011")
        and r.mint_mode in ("omit", "explicit_allowed")
    ]
    still_open = [r for r in loosen_cases if r.verdict == "STILL_OPEN"]
    fixed = [r for r in loosen_cases if r.verdict == "FIXED"]
    partial = [r for r in loosen_cases if r.verdict.startswith("PARTIAL")]

    lines = [
        "# RQA-6010 / RQA-6011 scope-loosen retest",
        "",
        f"- Run at: {datetime.now(UTC).isoformat()}",
        f"- Robot: {settings.robot_host} (https={settings.robot_use_https})",
        f"- Software: {robot_version or 'unknown'}",
        "",
        "## Summary",
        "",
        f"- Loosen cases (omit + explicit_allowed): {len(loosen_cases)}",
        f"- FIXED (scope + HTTP ok on same token): {len(fixed)}",
        f"- STILL_OPEN (403 / missing scope): {len(still_open)}",
        f"- PARTIAL (scope or HTTP only): {len(partial)}",
        "",
        "## Per-case results",
        "",
        "| Ticket | Mint | Path | Flag | Scope | Verdict | Introspect | HTTP |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        intro = "yes" if r.introspect_has_scope else "no"
        http = str(r.http_status) if r.http_status is not None else "n/a"
        lines.append(
            f"| {r.ticket} | {r.mint_mode} | {r.session_path} | {r.flag} | "
            f"{r.scope} | {r.verdict} | {intro} | {http} |"
        )

    lines.extend(["", "## Ticket conclusions", ""])
    r6010 = [r for r in loosen_cases if r.ticket == "RQA-6010"]
    r6011 = [r for r in loosen_cases if r.ticket == "RQA-6011"]
    for ticket, cases in (("RQA-6010", r6010), ("RQA-6011", r6011)):
        fixed_modes = [r.mint_mode for r in cases if r.verdict == "FIXED"]
        open_modes = [r.mint_mode for r in cases if r.verdict == "STILL_OPEN"]
        if fixed_modes and open_modes:
            status = (
                f"PARTIALLY FIXED ({', '.join(fixed_modes)} ok; "
                f"{', '.join(open_modes)} still open)"
            )
        elif fixed_modes:
            status = "FIXED on tested mint paths"
        elif open_modes:
            status = "STILL OPEN on tested mint paths"
        else:
            status = "INCONCLUSIVE"
        lines.append(f"- **{ticket}**: {status}")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- **FIXED**: existing token picks up scope after admin loosens flag "
            "and action succeeds.",
            "- **STILL_OPEN**: original bug; scope missing and/or 403 after loosen.",
            "- **PARTIAL_***: scope/enforcement mismatch; candidate for a new bug.",
            "- **INVALID_SCOPE_OK**: expected mint rejection while flag tightened.",
            "- **CONTROL_OK**: fresh remint after loosen still works.",
            "",
            "Artifacts: `results.json` in this directory.",
        ]
    )

    out_md = ART / "report.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out_json}")
    print(f"Wrote {out_md}")


async def main() -> int:
    global ART, PREFLIGHT, results
    parser = argparse.ArgumentParser(
        description="Retest RQA-6010 / RQA-6011 scope loosen"
    )
    parser.add_argument(
        "--6010-only",
        action="store_true",
        help="Run RQA-6010 cases only (signoff flag)",
    )
    parser.add_argument(
        "--prepare",
        action="store_true",
        help=(
            "Explicitly run provision-users (create-if-missing only). "
            "Default preflight does NOT provision or replace users."
        ),
    )
    parser.add_argument(
        "--replace-provision",
        action="store_true",
        help=(
            "With --prepare, delete and recreate fixture users (destructive; "
            "resets passwords; avoid for routine retests)"
        ),
    )
    parser.add_argument(
        "--skip-control",
        action="store_true",
        help="Skip CONTROL remint preflight",
    )
    parser.add_argument(
        "--dual-path",
        action="store_true",
        help="Omit mint only; compare cached access vs refresh_token after loosen",
    )
    parser.add_argument(
        "--mint-mode",
        action="append",
        choices=("omit", "explicit_allowed", "explicit_with_gated"),
        dest="mint_modes",
        help="Run only selected mint mode(s); repeatable",
    )
    args = parser.parse_args()

    if args.__dict__["6010_only"]:
        ART = Path("artifacts/retest-rqa6010-scope-mint")
    else:
        ART = DEFAULT_ART
    results = []

    ART.mkdir(parents=True, exist_ok=True)
    settings = await settings_with_resolved_host(get_settings())
    if not settings.allow_mutations:
        print("ERROR: set ALLOW_MUTATIONS=true before running this retest.")
        return 2
    if not settings.robot_use_https:
        print("WARN: ROBOT_USE_HTTPS=false; CRS-on tests should use HTTPS.")

    if args.prepare:
        await prepare_fixture_users(settings, replace=args.replace_provision)

    PREFLIGHT = await run_fixture_preflight(
        settings,
        usernames=(ADMIN, OPERATOR),
        repair=True,
    )
    print_fixture_preflight(PREFLIGHT)
    if not PREFLIGHT.ok:
        print(f"ERROR: fixture preflight failed: {PREFLIGHT.detail}")
        return 2

    robot_version: str | None = None
    try:
        admin_token = await fresh_admin_token(settings)
        async with FlexRobot(settings, access_token=admin_token) as admin:
            health = await admin.health.get_health()
            robot_version = health.system_version or health.api_version
    except Exception as exc:
        print(f"WARN: could not read robot version: {exc}")

    print(
        "Mint modes:\n"
        "  omit                 — no scope field (harness / agent default)\n"
        "  explicit_allowed     — request currently-allowed scopes only\n"
        "  explicit_with_gated  — also request gated write scopes (expect "
        "invalid_scope while tightened)\n"
        "  CONTROL              — remint after loosen (omit + explicit_with_gated)"
    )
    print(
        f"Robot host: {settings.robot_host} https={settings.robot_use_https} "
        f"version={robot_version}"
    )

    only_6010 = args.__dict__["6010_only"]
    dual_path = args.dual_path
    if dual_path:
        ART = Path("artifacts/retest-rqa6010-6011-dual-path")
        ART.mkdir(parents=True, exist_ok=True)
    if not args.skip_control and not only_6010 and not dual_path:
        await remint_controls(settings)
    if args.mint_modes:
        mint_modes = tuple(args.mint_modes)
    elif dual_path:
        mint_modes = ("omit",)
    else:
        mint_modes = ("omit", "explicit_allowed", "explicit_with_gated")
    for mint_mode in mint_modes:
        await run_6010(settings, mint_mode=mint_mode)
        if not only_6010:
            await run_6011(settings, mint_mode=mint_mode)

    write_report(settings, robot_version=robot_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
