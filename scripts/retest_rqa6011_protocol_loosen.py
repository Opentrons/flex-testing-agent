#!/usr/bin/env python3
"""Focused retest for RQA-6011: loosen requireAdminCredsWhenSendingProtocolToRobot.

When an admin turns the flag off, an operator who is already logged in should
be able to upload/send a protocol without re-login.

Maps to https://opentrons.atlassian.net/browse/RQA-6011

Flow modes (``--flow``):

  app (default)
    Matches manual App/ODD testing: flag already true, operator logged in,
    upload blocked, admin loosens flag, operator retries with the same token.

  stale-token
    Canonical stale-session path: login while flag false (token has
    ``protocols.write``), admin tightens (scope revoked), admin loosens,
    same token should work again.

  jira-repro
    Original Jira reproducer: tighten first, mint operator token under
    restriction, loosen, retry. Tokens minted under restriction may never
    receive ``protocols.write`` on loosen (different from App stale session).

Pass criteria: operator ``POST /protocols`` returns **201** after loosen on the
**same cached access token** (matches what you observe in the App). Introspect
scope is printed for diagnosis but is not required for PASS.

Preconditions:
  - CRS on, ROBOT_USE_HTTPS=true, ALLOW_MUTATIONS=true
  - flex_test_admin + flex_test_operator fixture users

Fixture hygiene: runs ``run_fixture_preflight`` first (inspect users + auth
settings; repair only when locked or neither lab password works). Does not
provision or replace users. See ``docs/crs-on-setup.md#fixture-user-hygiene``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from flex_testing_agent.capabilities.fixture_preflight import (
    FixturePreflightResult,
    access_token_for_fixture_user,
    ropc_token_for_fixture_user,
    run_fixture_preflight,
)
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.config.settings import Settings, get_settings
from flex_testing_agent.fixtures.auth_settings_suite import default_smoke_protocol_path
from flex_testing_agent.models.auth_settings import AuthSettingsData
from flex_testing_agent.models.auth_users import TokenIntrospectionResponse
from flex_testing_agent.orchestration.discover import settings_with_resolved_host
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session

ADMIN = "flex_test_admin"
OPERATOR = "flex_test_operator"
FLAG = "requireAdminCredsWhenSendingProtocolToRobot"
SCOPE = "protocols.write"
SMOKE = default_smoke_protocol_path()
JIRA = "https://opentrons.atlassian.net/browse/RQA-6011"
ART = Path("artifacts/retest-rqa6011-protocol-loosen")

console = Console()


class FlowMode(StrEnum):
    APP = "app"
    STALE_TOKEN = "stale-token"
    JIRA_REPRO = "jira-repro"


FLOW_HELP = {
    FlowMode.APP: (
        "Flag true → operator login → upload 403 → admin loosen → retry upload"
    ),
    FlowMode.STALE_TOKEN: (
        "Flag false → login with protocols.write → tighten revokes → loosen restores"
    ),
    FlowMode.JIRA_REPRO: "Tighten → mint under restriction → loosen → retry",
}


@dataclass
class StepResult:
    step: str
    introspect_scopes: list[str]
    has_scope: bool
    http_status: int | None
    detail: str
    response_body: dict[str, Any] | str | None = None


@dataclass
class SessionState:
    access_token: str
    refresh_token: str | None
    token_scope: str


def _redact_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    for key in ("access_token", "refresh_token", "token"):
        value = redacted.get(key)
        if isinstance(value, str) and len(value) > 16:
            redacted[key] = f"{value[:8]}...{value[-4:]} ({len(value)} chars)"
    return redacted


def _to_jsonable(body: object) -> dict[str, Any] | str:
    if isinstance(body, str):
        return body
    if isinstance(body, dict):
        return body
    model_dump = getattr(body, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    return {"value": str(body)}


def _print_json(title: str, body: object, *, redact: bool = False) -> None:
    payload = _to_jsonable(body)
    if isinstance(payload, dict) and redact:
        payload = _redact_secrets(payload)
    text = json.dumps(payload, indent=2, default=str)
    console.print(
        Panel(
            Syntax(text, "json", theme="monokai", word_wrap=True),
            title=title,
            border_style="blue",
        )
    )


def _step_rule(step: int, total: int, label: str) -> None:
    console.rule(f"[bold cyan][{step}/{total}] {label}[/bold cyan]")


def _print_step(step: StepResult) -> None:
    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("step", step.step)
    table.add_row(SCOPE, "[green]yes[/green]" if step.has_scope else "[red]no[/red]")
    table.add_row("introspect scopes", ", ".join(step.introspect_scopes) or "(none)")
    http = str(step.http_status) if step.http_status is not None else "n/a"
    table.add_row("HTTP", http)
    table.add_row("detail", step.detail)
    console.print(table)
    if step.response_body is not None:
        _print_json(f"{step.step} response body", step.response_body)


def _print_preflight(preflight: FixturePreflightResult) -> None:
    settings_table = Table(title="Auth settings snapshot", expand=True)
    settings_table.add_column("Setting")
    settings_table.add_column("Value")
    auth = preflight.auth_settings
    settings_table.add_row(FLAG, str(auth.require_admin_creds_when_sending_protocol_to_robot))
    settings_table.add_row(
        "requireAdminCredsWhenUpdatingRobotSoftware",
        str(auth.require_admin_creds_when_updating_robot_software),
    )
    settings_table.add_row(
        "requireAdminCredsForSignoffProtocol",
        str(auth.require_admin_creds_for_signoff_protocol),
    )
    settings_table.add_row("idleLogout (seconds)", str(auth.idle_logout))
    console.print(settings_table)

    users_table = Table(title="Fixture users", expand=True)
    users_table.add_column("User")
    users_table.add_column("Exists")
    users_table.add_column("Locked")
    users_table.add_column("resetPassword")
    users_table.add_column("Primary ROPC")
    users_table.add_column("Alt ROPC")
    users_table.add_column("Working cred")
    for user in preflight.users:
        users_table.add_row(
            user.username,
            "yes" if user.exists else "no",
            "n/a" if user.locked is None else str(user.locked),
            "n/a" if user.reset_password is None else str(user.reset_password),
            user.primary_probe,
            user.alternate_probe,
            user.working_credential or "(none)",
        )
    console.print(users_table)
    if preflight.repairs_performed:
        console.print("[yellow]Repairs performed:[/yellow]")
        for action in preflight.repairs_performed:
            console.print(f"  - {action}")
    console.print(f"Preflight: [bold]{preflight.detail}[/bold]")


def _split_scopes(scope: str | None) -> list[str]:
    if not scope:
        return []
    return scope.split()


def _introspect_body(intro: TokenIntrospectionResponse) -> dict[str, Any]:
    return intro.model_dump(mode="json", exclude_none=False)


async def _restore_settings(
    settings: Settings,
    baseline: AuthSettingsData,
    *,
    preflight: FixturePreflightResult,
) -> None:
    for attempt in (1, 2):
        admin_token = await access_token_for_fixture_user(
            settings,
            ADMIN,
            inspection=preflight.inspection_for(ADMIN),
        )
        try:
            async with FlexRobot(settings, access_token=admin_token) as admin:
                await admin.auth_settings.patch_settings(baseline.patch_fields())
            return
        except RobotApiError as exc:
            if attempt == 1 and exc.status_code == 401:
                continue
            console.print(
                f"[yellow]WARN[/yellow]: could not restore auth settings: "
                f"HTTP {exc.status_code}"
            )
            if exc.body:
                _print_json("restore error body", exc.body)
            return


async def _introspect_step(
    admin: FlexRobot,
    *,
    step: str,
    token: str,
    detail: str,
) -> StepResult:
    intro = await admin.oauth.introspect_token(token)
    scopes = _split_scopes(intro.scope)
    result = StepResult(
        step=step,
        introspect_scopes=scopes,
        has_scope=SCOPE in scopes,
        http_status=None,
        detail=detail,
        response_body=_introspect_body(intro),
    )
    _print_step(result)
    return result


async def _upload_step(
    settings: Settings,
    admin: FlexRobot,
    *,
    step: str,
    token: str,
    intro_scopes: list[str],
    has_scope: bool,
    detail: str,
) -> tuple[StepResult, str | None]:
    uploaded_protocol_id: str | None = None
    http_status: int | None
    response_body: dict[str, Any] | str
    detail_out: str
    async with FlexRobot(settings, access_token=token) as op:
        try:
            uploaded = await op.protocols.upload_protocol(SMOKE)
            http_status = 201
            detail_out = "upload ok"
            if isinstance(uploaded, dict):
                response_body = uploaded
                data = uploaded.get("data")
                if isinstance(data, dict) and data.get("id"):
                    uploaded_protocol_id = str(data["id"])
            else:
                response_body = {"raw": uploaded}
        except RobotApiError as exc:
            http_status = exc.status_code
            detail_out = exc.body or f"HTTP {exc.status_code}"
            response_body = exc.body or {"status_code": exc.status_code}

    result = StepResult(
        step=step,
        introspect_scopes=intro_scopes,
        has_scope=has_scope,
        http_status=http_status,
        detail=detail_out if isinstance(detail_out, str) else str(detail_out),
        response_body=response_body,
    )
    _print_step(result)
    return result, uploaded_protocol_id


async def _login_operator(
    settings: Settings,
    admin: FlexRobot,
    *,
    preflight: FixturePreflightResult,
    step: int,
    total: int,
    label: str,
) -> SessionState:
    _step_rule(step, total, label)
    token_response = await ropc_token_for_fixture_user(
        settings,
        OPERATOR,
        inspection=preflight.inspection_for(OPERATOR),
    )
    _print_json("POST /auth/oauth2/token response", token_response, redact=True)
    console.print("[dim]Caching access token for the rest of this run.[/dim]")
    intro = await admin.oauth.introspect_token(token_response.access_token)
    scopes = _split_scopes(intro.scope)
    console.print(
        f"Initial introspect: {SCOPE}="
        f"{'[green]yes[/green]' if SCOPE in scopes else '[red]no[/red]'} "
        f"scopes={scopes}"
    )
    return SessionState(
        access_token=token_response.access_token,
        refresh_token=token_response.refresh_token,
        token_scope=token_response.scope,
    )


async def _patch_flag(
    admin: FlexRobot,
    *,
    step: int,
    total: int,
    enabled: bool,
) -> AuthSettingsData:
    label = f"Admin PATCH {FLAG}={str(enabled).lower()}"
    _step_rule(step, total, label)
    updated = await admin.auth_settings.patch_settings({FLAG: enabled})
    _print_json(f"PATCH /auth/settings ({'tighten' if enabled else 'loosen'})", updated)
    return updated


def _summarize(
    *,
    flow: FlowMode,
    upload_status: int | None,
    has_scope_after_loosen: bool,
) -> tuple[bool, str]:
    upload_ok = upload_status == 201
    if upload_ok and has_scope_after_loosen:
        return True, f"{SCOPE} on introspect and upload HTTP 201 ({flow} flow)"
    if upload_ok and not has_scope_after_loosen:
        return (
            True,
            f"upload HTTP 201 after loosen ({flow} flow); "
            f"introspect still missing {SCOPE} (enforcement ok, introspect lag?)",
        )
    if not upload_ok and has_scope_after_loosen:
        return (
            False,
            f"{SCOPE} on introspect but upload HTTP {upload_status} "
            "(scope/enforcement mismatch)",
        )
    return (
        False,
        f"upload HTTP {upload_status} after loosen; "
        f"introspect missing {SCOPE} ({flow} flow)",
    )


async def _maybe_refresh_step(
    settings: Settings,
    admin: FlexRobot,
    session: SessionState,
    *,
    step: int,
    total: int,
) -> StepResult | None:
    if not session.refresh_token:
        console.print(
            "[yellow]No refresh_token in ROPC response; skipping refresh.[/yellow]"
        )
        return None
    _step_rule(step, total, "Refresh operator token (App may do this on retry)")
    async with build_robot_http_session(settings) as http_session:
        refreshed = await OAuthClient(http_session).refresh_access_token(
            session.refresh_token,
        )
    _print_json("POST /auth/oauth2/token (refresh)", refreshed, redact=True)
    intro = await admin.oauth.introspect_token(refreshed.access_token)
    scopes = _split_scopes(intro.scope)
    upload_result, uploaded_id = await _upload_step(
        settings,
        admin,
        step="upload_after_refresh",
        token=refreshed.access_token,
        intro_scopes=scopes,
        has_scope=SCOPE in scopes,
        detail="upload using refreshed access token",
    )
    if uploaded_id:
        with contextlib.suppress(RobotApiError):
            await admin.protocols.delete_protocol(uploaded_id)
    return upload_result


async def run_app_flow(
    settings: Settings,
    *,
    preflight: FixturePreflightResult,
    include_refresh: bool,
) -> tuple[bool, list[StepResult], str, FlowMode]:
    steps: list[StepResult] = []
    uploaded_protocol_id: str | None = None
    total = 7 if include_refresh else 6

    admin_token = await access_token_for_fixture_user(
        settings,
        ADMIN,
        inspection=preflight.inspection_for(ADMIN),
    )
    async with FlexRobot(settings, access_token=admin_token) as admin:
        baseline = await admin.auth_settings.get_settings()
        try:
            await _patch_flag(admin, step=1, total=total, enabled=True)
            session = await _login_operator(
                settings,
                admin,
                preflight=preflight,
                step=2,
                total=total,
                label=f"Operator login while {FLAG}=true ({OPERATOR}, no scope field)",
            )

            _step_rule(3, total, f"Upload while restricted ({SMOKE.name})")
            blocked, uploaded_protocol_id = await _upload_step(
                settings,
                admin,
                step="upload_while_tight",
                token=session.access_token,
                intro_scopes=_split_scopes(session.token_scope),
                has_scope=SCOPE in _split_scopes(session.token_scope),
                detail=f"{FLAG}=true; expect 403",
            )
            steps.append(blocked)

            await _patch_flag(admin, step=4, total=total, enabled=False)
            loosen_intro = await _introspect_step(
                admin,
                step="after_loosen_introspect",
                token=session.access_token,
                detail=f"{FLAG}=false; same access token as login",
            )
            steps.append(loosen_intro)

            _step_rule(5, total, f"Retry upload with same access token ({SMOKE.name})")
            upload_step, new_id = await _upload_step(
                settings,
                admin,
                step="upload_after_loosen",
                token=session.access_token,
                intro_scopes=loosen_intro.introspect_scopes,
                has_scope=loosen_intro.has_scope,
                detail="same cached access token after admin loosened flag",
            )
            steps.append(upload_step)
            uploaded_protocol_id = new_id or uploaded_protocol_id

            if include_refresh:
                refresh_step = await _maybe_refresh_step(
                    settings,
                    admin,
                    session,
                    step=6,
                    total=total,
                )
                if refresh_step is not None:
                    steps.append(refresh_step)
        finally:
            console.rule("[dim]cleanup[/dim]")
            if uploaded_protocol_id:
                with contextlib.suppress(RobotApiError):
                    await admin.protocols.delete_protocol(uploaded_protocol_id)
            await _restore_settings(settings, baseline, preflight=preflight)

    loosen_intro = next(
        (s for s in steps if s.step == "after_loosen_introspect"),
        steps[-1],
    )
    upload_step = next(
        (s for s in steps if s.step == "upload_after_loosen"),
        steps[-1],
    )
    ok, summary = _summarize(
        flow=FlowMode.APP,
        upload_status=upload_step.http_status,
        has_scope_after_loosen=loosen_intro.has_scope,
    )
    return ok, steps, summary, FlowMode.APP


async def run_stale_token_flow(
    settings: Settings,
    *,
    preflight: FixturePreflightResult,
    include_refresh: bool,
) -> tuple[bool, list[StepResult], str, FlowMode]:
    steps: list[StepResult] = []
    uploaded_protocol_id: str | None = None
    total = 8 if include_refresh else 7

    admin_token = await access_token_for_fixture_user(
        settings,
        ADMIN,
        inspection=preflight.inspection_for(ADMIN),
    )
    async with FlexRobot(settings, access_token=admin_token) as admin:
        baseline = await admin.auth_settings.get_settings()
        try:
            await _patch_flag(admin, step=1, total=total, enabled=False)
            session = await _login_operator(
                settings,
                admin,
                preflight=preflight,
                step=2,
                total=total,
                label=f"Operator login while {FLAG}=false (expect {SCOPE})",
            )
            if SCOPE not in _split_scopes(session.token_scope):
                console.print(
                    "[yellow]WARN[/yellow]: token minted without "
                    f"{SCOPE} even with flag false; stale-token path may "
                    "not apply on this build."
                )

            await _patch_flag(admin, step=3, total=total, enabled=True)
            revoked = await _introspect_step(
                admin,
                step="after_tighten_introspect",
                token=session.access_token,
                detail=f"{FLAG}=true; expect {SCOPE} revoked on same token",
            )
            steps.append(revoked)

            _step_rule(4, total, f"Upload while restricted ({SMOKE.name})")
            blocked, _ = await _upload_step(
                settings,
                admin,
                step="upload_while_tight",
                token=session.access_token,
                intro_scopes=revoked.introspect_scopes,
                has_scope=revoked.has_scope,
                detail="expect 403 after tighten revoked scope",
            )
            steps.append(blocked)

            await _patch_flag(admin, step=5, total=total, enabled=False)
            loosen_intro = await _introspect_step(
                admin,
                step="after_loosen_introspect",
                token=session.access_token,
                detail=f"{FLAG}=false; expect {SCOPE} restored on same token",
            )
            steps.append(loosen_intro)

            _step_rule(6, total, f"Retry upload with same access token ({SMOKE.name})")
            upload_step, uploaded_protocol_id = await _upload_step(
                settings,
                admin,
                step="upload_after_loosen",
                token=session.access_token,
                intro_scopes=loosen_intro.introspect_scopes,
                has_scope=loosen_intro.has_scope,
                detail="same cached access token after admin loosened flag",
            )
            steps.append(upload_step)

            if include_refresh:
                refresh_step = await _maybe_refresh_step(
                    settings,
                    admin,
                    session,
                    step=7,
                    total=total,
                )
                if refresh_step is not None:
                    steps.append(refresh_step)
        finally:
            console.rule("[dim]cleanup[/dim]")
            if uploaded_protocol_id:
                with contextlib.suppress(RobotApiError):
                    await admin.protocols.delete_protocol(uploaded_protocol_id)
            await _restore_settings(settings, baseline, preflight=preflight)

    loosen_intro = next(
        (s for s in steps if s.step == "after_loosen_introspect"),
        steps[-1],
    )
    upload_step = next(
        (s for s in steps if s.step == "upload_after_loosen"),
        steps[-1],
    )
    ok, summary = _summarize(
        flow=FlowMode.STALE_TOKEN,
        upload_status=upload_step.http_status,
        has_scope_after_loosen=loosen_intro.has_scope,
    )
    return ok, steps, summary, FlowMode.STALE_TOKEN


async def run_jira_repro_flow(
    settings: Settings,
    *,
    preflight: FixturePreflightResult,
) -> tuple[bool, list[StepResult], str, FlowMode]:
    """Mint-after-tighten path from the Jira ticket (may not match App UX)."""
    steps: list[StepResult] = []
    uploaded_protocol_id: str | None = None
    total = 6

    admin_token = await access_token_for_fixture_user(
        settings,
        ADMIN,
        inspection=preflight.inspection_for(ADMIN),
    )
    async with FlexRobot(settings, access_token=admin_token) as admin:
        baseline = await admin.auth_settings.get_settings()
        try:
            await _patch_flag(admin, step=1, total=total, enabled=True)
            session = await _login_operator(
                settings,
                admin,
                preflight=preflight,
                step=2,
                total=total,
                label=f"Mint operator token while {FLAG}=true",
            )
            _step_rule(
                3,
                total,
                "Introspect minted token (expect protocols.write absent)",
            )
            tighten_intro = await _introspect_step(
                admin,
                step="after_tighten_introspect",
                token=session.access_token,
                detail=f"mint under {FLAG}=true; expect {SCOPE} absent",
            )
            steps.append(tighten_intro)

            await _patch_flag(admin, step=4, total=total, enabled=False)
            loosen_intro = await _introspect_step(
                admin,
                step="after_loosen_introspect",
                token=session.access_token,
                detail=f"{FLAG}=false; expect {SCOPE} on same minted token",
            )
            steps.append(loosen_intro)

            _step_rule(5, total, f"Upload with same access token ({SMOKE.name})")
            upload_step, uploaded_protocol_id = await _upload_step(
                settings,
                admin,
                step="upload_after_loosen",
                token=session.access_token,
                intro_scopes=loosen_intro.introspect_scopes,
                has_scope=loosen_intro.has_scope,
                detail="jira-repro: token minted while flag was true",
            )
            steps.append(upload_step)
        finally:
            console.rule("[dim]cleanup[/dim]")
            if uploaded_protocol_id:
                with contextlib.suppress(RobotApiError):
                    await admin.protocols.delete_protocol(uploaded_protocol_id)
            await _restore_settings(settings, baseline, preflight=preflight)

    upload_step = steps[-1]
    loosen_intro = next(
        (s for s in steps if s.step == "after_loosen_introspect"),
        upload_step,
    )
    ok, summary = _summarize(
        flow=FlowMode.JIRA_REPRO,
        upload_status=upload_step.http_status,
        has_scope_after_loosen=loosen_intro.has_scope,
    )
    return ok, steps, summary, FlowMode.JIRA_REPRO


async def run_retest(
    settings: Settings,
    *,
    preflight: FixturePreflightResult,
    flow: FlowMode,
    include_refresh: bool,
) -> tuple[bool, list[StepResult], str, FlowMode]:
    if flow is FlowMode.APP:
        return await run_app_flow(
            settings,
            preflight=preflight,
            include_refresh=include_refresh,
        )
    if flow is FlowMode.STALE_TOKEN:
        return await run_stale_token_flow(
            settings,
            preflight=preflight,
            include_refresh=include_refresh,
        )
    return await run_jira_repro_flow(settings, preflight=preflight)


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retest RQA-6011 protocol-upload scope loosen",
    )
    parser.add_argument(
        "--flow",
        choices=tuple(FlowMode),
        default=FlowMode.APP,
        help="Test path (default: app — matches manual App/ODD testing)",
    )
    parser.add_argument(
        "--include-refresh",
        action="store_true",
        help="Also try refresh_token grant after loosen (App may refresh on retry)",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ART,
        help=f"Write results.json here (default: {ART})",
    )
    args = parser.parse_args()
    flow = FlowMode(args.flow)
    artifact_dir = args.artifact_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)

    settings = await settings_with_resolved_host(get_settings())
    console.print(
        Panel(
            f"[bold]RQA-6011 protocol-upload loosen retest[/bold]\n{JIRA}\n\n"
            f"Flow: [cyan]{flow}[/cyan] — {FLOW_HELP[flow]}\n"
            f"Robot: {settings.robot_host}\n"
            f"HTTPS: {settings.robot_use_https}\n"
            f"Mutations: {settings.allow_mutations}",
            border_style="green",
        )
    )
    if not settings.allow_mutations:
        console.print("[red]ERROR[/red]: set ALLOW_MUTATIONS=true before running.")
        return 2
    if not settings.robot_use_https:
        console.print(
            "[yellow]WARN[/yellow]: ROBOT_USE_HTTPS=false; "
            "CRS-on tests should use HTTPS."
        )

    console.rule("[bold]Fixture preflight[/bold]")
    preflight = await run_fixture_preflight(
        settings,
        usernames=(ADMIN, OPERATOR),
        repair=True,
    )
    _print_preflight(preflight)
    if not preflight.ok:
        console.print(
            Panel(
                f"[red]Preflight failed[/red]\n{preflight.detail}\n\n"
                "Fix fixture users manually or run "
                "`flex-test crs provision-users` for missing accounts. "
                "Preflight does not recreate users automatically.",
                border_style="red",
            )
        )
        return 2

    robot_version: str | None = None
    try:
        admin_token = await access_token_for_fixture_user(
            settings,
            ADMIN,
            inspection=preflight.inspection_for(ADMIN),
        )
        async with FlexRobot(settings, access_token=admin_token) as admin:
            health = await admin.health.get_health()
            robot_version = health.system_version or health.api_version
        console.print(f"Software: [bold]{robot_version or 'unknown'}[/bold]")
    except Exception as exc:
        console.print(f"[yellow]WARN[/yellow]: could not read robot version: {exc}")

    ok, step_results, summary, flow_used = await run_retest(
        settings,
        preflight=preflight,
        flow=flow,
        include_refresh=args.include_refresh,
    )

    verdict = "PASS" if ok else "BUG_STILL_OPEN"
    style = "bold green" if ok else "bold red"
    border = "green" if ok else "red"
    console.print(
        Panel(f"[{style}]{verdict}[/{style}]\n{summary}", border_style=border)
    )
    if flow is FlowMode.JIRA_REPRO and not ok:
        console.print(
            "[dim]Note: jira-repro mints under restriction. If --flow app passes "
            "but jira-repro fails, the product may only restore scopes for "
            "sessions that previously held them (stale-token path).[/dim]"
        )

    report = {
        "ticket": "RQA-6011",
        "flag": FLAG,
        "scope": SCOPE,
        "flow": flow_used,
        "preflight": preflight.to_evidence(),
        "robot_host": settings.robot_host,
        "robot_version": robot_version,
        "ok": ok,
        "verdict": verdict,
        "summary": summary,
        "steps": [asdict(s) for s in step_results],
    }
    out = artifact_dir / "results.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    console.print(f"\nWrote [cyan]{out}[/cyan]")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
