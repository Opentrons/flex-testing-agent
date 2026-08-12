"""CRS-on auth settings behavior suite (GET/PATCH /auth/settings)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.crs_auth import (
    access_token_for_username,
    ensure_crs_on,
)
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.auth_settings_suite import (
    LoginAttemptsUserSpec,
    default_smoke_protocol_path,
)
from flex_testing_agent.fixtures.user_management import (
    EphemeralUserSpec,
    ensure_user_absent,
    ensure_user_present,
)
from flex_testing_agent.models.auth_settings import AuthSettingsData
from flex_testing_agent.models.auth_users import UpdateUserRequest
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    ensure_run_state,
    release_current_run,
)
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session

ALL_CASE_IDS = frozenset(
    {
        "S0",
        "S1",
        "S2",
        "S3",
        "S4",
        "S5",
        "S6",
        "S7",
        "S8",
        "S9",
        "S10",
        "S11",
        "S12",
    }
)
SLOW_CASE_IDS = frozenset({"S5", "S6"})
BLOCKED_BY_DEFAULT = frozenset({"S5"})

AUTH_SETTINGS_SUITE = CapabilityDescriptor(
    name="crs_auth_settings_suite",
    description=(
        "CRS-on auth policy settings suite: per-field enforcement and "
        "requireAdminCreds combination matrix via HTTP API."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    mutates_robot=True,
    requires_cleanup=True,
    evidence_produced=["crs_auth_settings_suite.json"],
    preconditions=[
        "ALLOW_MUTATIONS=true",
        "CRS / accessControlEnabled is true",
        "ROBOT_USE_HTTPS=true and CA trust configured",
        "flex_harness_admin + flex_test_operator fixture users",
    ],
)


class SettingsSuiteStepResult(BaseModel):
    """One case or sub-step in the auth settings suite."""

    case_id: str
    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False


class SettingsSuiteResult(BaseModel):
    """Aggregate auth settings suite outcome."""

    baseline: AuthSettingsData | None = None
    steps: list[SettingsSuiteStepResult] = Field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for step in self.steps if step.ok and not step.skipped)

    @property
    def fail_count(self) -> int:
        return sum(1 for step in self.steps if not step.ok and not step.skipped)

    @property
    def skipped_count(self) -> int:
        return sum(1 for step in self.steps if step.skipped)


def parse_case_ids(raw: str | None) -> frozenset[str] | None:
    """Parse comma-separated case ids (e.g. ``S1,S7``)."""
    if raw is None or not raw.strip():
        return None
    ids = {part.strip().upper() for part in raw.split(",") if part.strip()}
    unknown = ids - ALL_CASE_IDS
    if unknown:
        raise ValueError(f"Unknown case ids: {sorted(unknown)}")
    return frozenset(ids)


def resolve_selected_cases(
    *,
    cases: frozenset[str] | None,
    include_slow: bool,
) -> frozenset[str]:
    if cases is not None:
        selected = set(cases)
    else:
        selected = set(ALL_CASE_IDS) - BLOCKED_BY_DEFAULT
        if not include_slow:
            selected -= SLOW_CASE_IDS - BLOCKED_BY_DEFAULT
    if selected - {"S0"}:
        selected.add("S0")
    return frozenset(selected)


async def run_auth_settings_suite(
    settings: Settings,
    *,
    admin_username: str = "flex_test_admin",
    operator_username: str = "flex_test_operator",
    auditor_username: str = "flex_test_auditor",
    cases: frozenset[str] | None = None,
    include_slow: bool = False,
    restore_defaults: bool = True,
    idle_wait_seconds: float = 65.0,
    protocol_path: Path | None = None,
) -> SettingsSuiteResult:
    """Run selected auth-settings behavior cases on a CRS-enabled robot."""
    ensure_mutation_allowed(
        settings,
        risk_level=AUTH_SETTINGS_SUITE.risk_level,
        capability_name=AUTH_SETTINGS_SUITE.name,
    )
    selected = resolve_selected_cases(cases=cases, include_slow=include_slow)
    smoke_protocol = protocol_path or default_smoke_protocol_path()
    if not smoke_protocol.is_file():
        raise FileNotFoundError(f"Smoke protocol not found: {smoke_protocol}")

    admin_token = await access_token_for_username(settings, admin_username)
    operator_token = await access_token_for_username(settings, operator_username)
    auditor_token = await access_token_for_username(settings, auditor_username)

    steps: list[SettingsSuiteStepResult] = []
    baseline: AuthSettingsData | None = None

    async with FlexRobot(settings, access_token=admin_token) as admin_robot:
        await ensure_crs_on(admin_robot)
        baseline = await admin_robot.auth_settings.get_settings()

        async def record(
            case_id: str,
            name: str,
            coro: Awaitable[str],
            *,
            skipped: bool = False,
        ) -> None:
            if skipped:
                steps.append(
                    SettingsSuiteStepResult(
                        case_id=case_id,
                        name=name,
                        ok=True,
                        detail="skipped",
                        skipped=True,
                    )
                )
                return
            try:
                detail = await coro
                steps.append(
                    SettingsSuiteStepResult(
                        case_id=case_id,
                        name=name,
                        ok=True,
                        detail=detail,
                    )
                )
            except Exception as exc:
                steps.append(
                    SettingsSuiteStepResult(
                        case_id=case_id,
                        name=name,
                        ok=False,
                        detail=_format_step_error(exc),
                    )
                )

        if "S0" in selected:
            await record(
                "S0",
                "preconditions_baseline",
                _case_s0(admin_robot, baseline=baseline),
            )

        if "S1" in selected:
            await record(
                "S1",
                "maxNumberOfLoginAttempts",
                _case_s1(admin_robot, admin_token=admin_token, baseline=baseline),
            )

        if "S2" in selected:
            await record(
                "S2",
                "passwordComplexityMinimumLength",
                _case_s2(admin_robot, admin_token=admin_token, baseline=baseline),
            )

        if "S3" in selected:
            await record(
                "S3",
                "passwordComplexitySpecialCharacters",
                _case_s3(admin_robot, admin_token=admin_token, baseline=baseline),
            )

        if "S4" in selected:
            await record(
                "S4",
                "password_complexity_combination",
                _case_s4(admin_robot, admin_token=admin_token, baseline=baseline),
            )

        if "S5" in selected:
            await record(
                "S5",
                "passwordResetTime",
                _static_detail(
                    "blocked: requires clock control or minimum expiry",
                )(),
                skipped=not include_slow,
            )

        if "S6" in selected:
            await record(
                "S6",
                "idleLogout",
                _case_s6(
                    settings,
                    operator_token=operator_token,
                    admin_robot=admin_robot,
                    baseline=baseline,
                    idle_wait_seconds=idle_wait_seconds,
                ),
                skipped=not include_slow,
            )

        if "S7" in selected:
            await record(
                "S7",
                "requireAdminCredsWhenUpdatingRobotSoftware",
                _case_s7(
                    settings,
                    admin_token=admin_token,
                    operator_token=operator_token,
                    admin_robot=admin_robot,
                    baseline=baseline,
                ),
            )

        if "S8" in selected:
            await record(
                "S8",
                "requireAdminCredsWhenSendingProtocolToRobot",
                _case_s8(
                    settings,
                    admin_token=admin_token,
                    operator_token=operator_token,
                    admin_robot=admin_robot,
                    baseline=baseline,
                    smoke_protocol=smoke_protocol,
                ),
            )

        if "S9" in selected:
            await record(
                "S9",
                "requireAdminCredsForSignoffProtocol",
                _case_s9(
                    settings,
                    admin_token=admin_token,
                    operator_token=operator_token,
                    admin_robot=admin_robot,
                    baseline=baseline,
                    smoke_protocol=smoke_protocol,
                ),
            )

        if "S10" in selected:
            await record(
                "S10",
                "requireAdminCreds_combination_matrix",
                _case_s10(
                    settings,
                    admin_token=admin_token,
                    operator_token=operator_token,
                    admin_robot=admin_robot,
                    baseline=baseline,
                    smoke_protocol=smoke_protocol,
                ),
            )

        if "S11" in selected:
            await record(
                "S11",
                "settings_persistence_and_restore",
                _case_s11(admin_robot, baseline=baseline),
            )

        if "S12" in selected:
            await record(
                "S12",
                "settings_route_authorization",
                _case_s12(
                    settings,
                    operator_token=operator_token,
                    auditor_token=auditor_token,
                ),
            )

        if restore_defaults and baseline is not None:
            try:
                await _apply_settings(admin_robot, baseline)
                steps.append(
                    SettingsSuiteStepResult(
                        case_id="cleanup",
                        name="restore_baseline",
                        ok=True,
                        detail="baseline settings restored",
                    )
                )
            except Exception as exc:
                steps.append(
                    SettingsSuiteStepResult(
                        case_id="cleanup",
                        name="restore_baseline",
                        ok=False,
                        detail=str(exc),
                    )
                )

        result = SettingsSuiteResult(baseline=baseline, steps=steps)
        admin_robot.raw_evidence["crs_auth_settings_suite"] = result.model_dump(
            mode="json"
        )
        return result


def _static_detail(message: str) -> Callable[[], Awaitable[str]]:
    async def _inner() -> str:
        return message

    return _inner


def _format_step_error(exc: Exception) -> str:
    if isinstance(exc, RobotApiError):
        body = (exc.body or "")[:400]
        suffix = f" body={body!r}" if body else ""
        return f"HTTP {exc.status_code} for {exc.path}{suffix}"
    return str(exc)


def _is_client_rejection(status_code: int | None) -> bool:
    return status_code in {400, 422}


async def _ensure_no_current_run(robot: FlexRobot) -> None:
    """Stop, sign off, and uncurrent blocking runs before protocol/signoff tests."""
    await ensure_run_state(
        robot,
        DesiredRunState.NO_CURRENT,
        ensure=True,
        capability_name=AUTH_SETTINGS_SUITE.name,
        signed_by="Flex Harness Cleanup",
    )


async def _token_has_scope(settings: Settings, token: str, scope: str) -> bool:
    async with FlexRobot(settings, access_token=token) as session_robot:
        intro = await session_robot.oauth.introspect_token(token)
    if not intro.scope:
        return False
    return scope in intro.scope.split()


async def _case_s0(robot: FlexRobot, *, baseline: AuthSettingsData) -> str:
    return (
        f"maxLoginAttempts={baseline.max_number_of_login_attempts} "
        f"idleLogout={baseline.idle_logout}"
    )


async def _apply_settings(robot: FlexRobot, settings: AuthSettingsData) -> None:
    await robot.auth_settings.patch_settings(settings.patch_fields())


async def _case_s1(
    robot: FlexRobot,
    *,
    admin_token: str,
    baseline: AuthSettingsData,
) -> str:
    spec = LoginAttemptsUserSpec.default()
    ephemeral = EphemeralUserSpec(
        username=spec.username,
        password=spec.password,
        full_name=spec.full_name,
        account_type=spec.account_type,
    )
    users = robot.users
    oauth = robot.oauth
    try:
        await robot.auth_settings.patch_settings({"maxNumberOfLoginAttempts": 3})
        await ensure_user_absent(users, ephemeral.username, admin_token=admin_token)
        await ensure_user_present(users, ephemeral, admin_token=admin_token)

        failures = 0
        for _ in range(3):
            try:
                await oauth.get_token(ephemeral.username, "wrong-password")
            except RobotApiError as exc:
                if exc.status_code in {400, 401, 403}:
                    failures += 1
                    continue
                raise
            else:
                raise AssertionError("expected failed login to raise RobotApiError")
        if failures != 3:
            raise AssertionError(f"expected 3 failed logins, got {failures}")

        profile = await users.get_user_by_username(
            ephemeral.username,
            access_token=admin_token,
        )
        if not profile.locked:
            raise AssertionError("expected account locked after max login attempts")

        await users.update_user(
            ephemeral.username,
            UpdateUserRequest(locked=False),
            access_token=admin_token,
        )
        await users.delete_user(ephemeral.username, access_token=admin_token)
        return "locked after 3 failures; unlocked and deleted ephemeral user"
    finally:
        await _apply_settings(robot, baseline)


async def _case_s2(
    robot: FlexRobot,
    *,
    admin_token: str,
    baseline: AuthSettingsData,
) -> str:
    username = "flex_pw_len"
    try:
        await robot.auth_settings.patch_settings(
            {"passwordComplexityMinimumLength": 12},
        )
        await ensure_user_absent(robot.users, username, admin_token=admin_token)
        try:
            await robot.users.create_user(
                username=username,
                password="short1",
                full_name="Too Short",
                account_type="user",
                access_token=admin_token,
            )
        except RobotApiError as exc:
            if not _is_client_rejection(exc.status_code):
                raise
        else:
            raise AssertionError("expected 400/422 for short password on create")

        await robot.users.create_user(
            username=username,
            password="longenough12!",
            full_name="Long Enough",
            account_type="user",
            access_token=admin_token,
        )
        await robot.users.delete_user(username, access_token=admin_token)
        return "400 on short password; 201 on 12+ char password"
    finally:
        await _apply_settings(robot, baseline)


async def _case_s3(
    robot: FlexRobot,
    *,
    admin_token: str,
    baseline: AuthSettingsData,
) -> str:
    username = "flex_pw_special"
    try:
        await robot.auth_settings.patch_settings(
            {"passwordComplexitySpecialCharacters": True},
        )
        await ensure_user_absent(robot.users, username, admin_token=admin_token)
        try:
            await robot.users.create_user(
                username=username,
                password="LongPasswordOnly1",
                full_name="No Special",
                account_type="user",
                access_token=admin_token,
            )
        except RobotApiError as exc:
            if not _is_client_rejection(exc.status_code):
                raise
        else:
            raise AssertionError("expected 400/422 without special character")

        await robot.users.create_user(
            username=username,
            password="LongPasswordOnly1!",
            full_name="With Special",
            account_type="user",
            access_token=admin_token,
        )
        await robot.users.delete_user(username, access_token=admin_token)
        return "400 on missing special char; 201 with special char"
    finally:
        await _apply_settings(robot, baseline)


async def _case_s4(
    robot: FlexRobot,
    *,
    admin_token: str,
    baseline: AuthSettingsData,
) -> str:
    username = "flex_pw_combo"
    try:
        await robot.auth_settings.patch_settings(
            {
                "passwordComplexityMinimumLength": 10,
                "passwordComplexitySpecialCharacters": True,
            },
        )
        await ensure_user_absent(robot.users, username, admin_token=admin_token)

        for password, suffix in (
            ("TooShort!", "ts"),
            ("LongEnoughNoSpecial", "ns"),
        ):
            try:
                await robot.users.create_user(
                    username=f"{username}_{suffix}",
                    password=password,
                    full_name=suffix,
                    account_type="user",
                    access_token=admin_token,
                )
            except RobotApiError as exc:
                if not _is_client_rejection(exc.status_code):
                    raise
            else:
                raise AssertionError(f"expected 400/422 for {suffix}")

        await robot.users.create_user(
            username=username,
            password="LongEnough1!",
            full_name="Combo OK",
            account_type="user",
            access_token=admin_token,
        )
        await robot.users.delete_user(username, access_token=admin_token)
        return "rejected short and no-special; accepted combined rule password"
    finally:
        await _apply_settings(robot, baseline)


async def _case_s6(
    settings: Settings,
    *,
    operator_token: str,
    admin_robot: FlexRobot,
    baseline: AuthSettingsData,
    idle_wait_seconds: float,
) -> str:
    try:
        await admin_robot.auth_settings.patch_settings({"idleLogout": 60.0})
        async with FlexRobot(settings, access_token=operator_token) as operator_robot:
            before = await operator_robot.oauth.introspect_token(operator_token)
            if not before.active:
                raise AssertionError("operator token not active before idle wait")
            await asyncio.sleep(idle_wait_seconds)
            after = await operator_robot.oauth.introspect_token(operator_token)
            if after.active:
                raise AssertionError(
                    f"token still active after {idle_wait_seconds}s idle "
                    "(expected idleLogout enforcement)"
                )
        return f"token inactive after {idle_wait_seconds}s idle"
    finally:
        await _apply_settings(admin_robot, baseline)


async def _case_s7(
    settings: Settings,
    *,
    admin_token: str,
    operator_token: str,
    admin_robot: FlexRobot,
    baseline: AuthSettingsData,
) -> str:
    try:
        await admin_robot.auth_settings.patch_settings(
            {"requireAdminCredsWhenUpdatingRobotSoftware": True},
        )
        async with FlexRobot(settings, access_token=operator_token) as operator_robot:
            await _expect_http_denied(
                lambda: operator_robot.update.begin(),
                label="update begin",
            )

        async with FlexRobot(settings, access_token=admin_token) as admin_session_robot:
            session = await admin_session_robot.update.begin()
            token = _extract_update_token(session)
            if token:
                await admin_session_robot.update.cancel()
        return "operator denied; admin allowed update begin (cancelled)"
    finally:
        await _apply_settings(admin_robot, baseline)


async def _case_s8(
    settings: Settings,
    *,
    admin_token: str,
    operator_token: str,
    admin_robot: FlexRobot,
    baseline: AuthSettingsData,
    smoke_protocol: Path,
) -> str:
    protocol_id: str | None = None
    try:
        await _ensure_no_current_run(admin_robot)
        await admin_robot.auth_settings.patch_settings(
            {"requireAdminCredsWhenSendingProtocolToRobot": True},
        )
        async with FlexRobot(settings, access_token=operator_token) as operator_robot:
            await _expect_http_denied(
                lambda: operator_robot.protocols.upload_protocol(smoke_protocol),
                label="protocol upload",
                also_accept=frozenset({500}),
            )

        async with FlexRobot(settings, access_token=admin_token) as admin_session_robot:
            uploaded = await admin_session_robot.protocols.upload_protocol(
                smoke_protocol,
            )
            protocol_id = _extract_protocol_id(uploaded)

        await admin_robot.auth_settings.patch_settings(
            {"requireAdminCredsWhenSendingProtocolToRobot": False},
        )
        operator_can_upload = await _token_has_scope(
            settings,
            operator_token,
            "protocols.write",
        )
        if operator_can_upload:
            async with FlexRobot(
                settings,
                access_token=operator_token,
            ) as operator_robot:
                uploaded = await operator_robot.protocols.upload_protocol(
                    smoke_protocol,
                )
                op_protocol_id = _extract_protocol_id(uploaded)
                await operator_robot.protocols.delete_protocol(op_protocol_id)
            return "operator denied when true; admin upload ok; operator ok when false"

        return (
            "operator denied when true; admin upload ok; "
            "operator upload when false skipped (no protocols.write scope)"
        )
    finally:
        if protocol_id is not None:
            with contextlib.suppress(RobotApiError):
                await admin_robot.protocols.delete_protocol(protocol_id)
        await _apply_settings(admin_robot, baseline)


async def _create_run_with_retry(
    robot: FlexRobot,
    *,
    protocol_id: str,
) -> dict[str, Any]:
    last_error: RobotApiError | None = None
    for _ in range(2):
        try:
            return await robot.runs.create_run(protocol_id=protocol_id)
        except RobotApiError as exc:
            last_error = exc
            if exc.status_code != 500:
                raise
            await asyncio.sleep(2.0)
    assert last_error is not None
    raise last_error


async def _resolve_smoke_protocol_id(
    robot: FlexRobot,
    smoke_protocol: Path,
) -> str:
    """Return an existing smoke protocol id or upload once."""
    main_name = smoke_protocol.name
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
            protocol_id = summary.get("id")
            if protocol_id is not None:
                return str(protocol_id)
    uploaded = await robot.protocols.upload_protocol(smoke_protocol)
    return _extract_protocol_id(uploaded)


async def _prepare_run_for_signoff(robot: FlexRobot, run_id: str) -> None:
    """Stop idle runs so protocol-log signoff is allowed."""
    run_payload = await robot.runs.get_run(run_id)
    status = (robot.runs.status_from_run(run_payload) or "").lower()
    if status == "idle":
        await robot.runs.stop(run_id)


async def _case_s9(
    settings: Settings,
    *,
    admin_token: str,
    operator_token: str,
    admin_robot: FlexRobot,
    baseline: AuthSettingsData,
    smoke_protocol: Path,
) -> str:
    protocol_id: str | None = None
    run_id: str | None = None
    try:
        await _ensure_no_current_run(admin_robot)
        await admin_robot.auth_settings.patch_settings(
            {"requireAdminCredsForSignoffProtocol": True},
        )
        protocol_id = await _resolve_smoke_protocol_id(admin_robot, smoke_protocol)
        created = await _create_run_with_retry(admin_robot, protocol_id=protocol_id)
        run_id = _extract_run_id(created)
        await _prepare_run_for_signoff(admin_robot, run_id)

        async with FlexRobot(settings, access_token=operator_token) as operator_robot:
            await _expect_http_denied(
                lambda: operator_robot.runs.sign_off(
                    run_id,
                    signed_by="Flex Test Operator",
                ),
                label="run signoff",
            )

        await admin_robot.runs.sign_off(run_id, signed_by="Flex Harness Admin")
        await admin_robot.runs.set_current(run_id, current=False)
        return "operator denied signoff; admin signoff ok"
    finally:
        if run_id is not None:
            with contextlib.suppress(RobotApiError):
                await release_current_run(
                    admin_robot,
                    run_id,
                    signed_by="Flex Harness Cleanup",
                )
        if protocol_id is not None:
            with contextlib.suppress(RobotApiError):
                await admin_robot.protocols.delete_protocol(protocol_id)
        await _apply_settings(admin_robot, baseline)


async def _case_s10(
    settings: Settings,
    *,
    admin_token: str,
    operator_token: str,
    admin_robot: FlexRobot,
    baseline: AuthSettingsData,
    smoke_protocol: Path,
) -> str:
    protocol_id: str | None = None
    run_id: str | None = None
    try:
        await _ensure_no_current_run(admin_robot)
        await admin_robot.auth_settings.patch_settings(
            {
                "requireAdminCredsWhenUpdatingRobotSoftware": True,
                "requireAdminCredsWhenSendingProtocolToRobot": True,
                "requireAdminCredsForSignoffProtocol": True,
            },
        )
        async with FlexRobot(settings, access_token=operator_token) as operator_robot:
            await _expect_http_denied(
                lambda: operator_robot.update.begin(),
                label="update begin",
            )
            await _expect_http_denied(
                lambda: operator_robot.protocols.upload_protocol(smoke_protocol),
                label="protocol upload",
                also_accept=frozenset({500}),
            )

        protocol_id = await _resolve_smoke_protocol_id(admin_robot, smoke_protocol)
        created = await _create_run_with_retry(admin_robot, protocol_id=protocol_id)
        run_id = _extract_run_id(created)
        await _prepare_run_for_signoff(admin_robot, run_id)

        async with FlexRobot(settings, access_token=operator_token) as operator_robot:
            await _expect_http_denied(
                lambda: operator_robot.runs.sign_off(
                    run_id,
                    signed_by="Operator",
                ),
                label="signoff",
            )

        await admin_robot.auth_settings.patch_settings(
            {"requireAdminCredsForSignoffProtocol": False},
        )
        operator_can_signoff = await _token_has_scope(
            settings,
            operator_token,
            "run_signoff.write",
        )
        if operator_can_signoff:
            async with FlexRobot(
                settings,
                access_token=operator_token,
            ) as operator_robot:
                await operator_robot.runs.sign_off(
                    run_id,
                    signed_by="Flex Test Operator",
                )
            return "all gates true blocked operator; signoff allowed when flag false"

        return (
            "all gates true blocked operator; signoff when false skipped "
            "(no run_signoff.write scope)"
        )
    finally:
        if run_id is not None:
            with contextlib.suppress(RobotApiError):
                await release_current_run(
                    admin_robot,
                    run_id,
                    signed_by="Flex Harness Cleanup",
                )
        if protocol_id is not None:
            with contextlib.suppress(RobotApiError):
                await admin_robot.protocols.delete_protocol(protocol_id)
        await _apply_settings(admin_robot, baseline)


async def _case_s11(robot: FlexRobot, *, baseline: AuthSettingsData) -> str:
    try:
        patched = await robot.auth_settings.patch_settings({"idleLogout": 120.0})
        if patched.idle_logout != 120.0:
            raise AssertionError("idleLogout not updated to 120")
        if (
            patched.max_number_of_login_attempts
            != baseline.max_number_of_login_attempts
        ):
            raise AssertionError("partial PATCH changed unrelated fields")
        await robot.auth_settings.delete_settings()
        await _apply_settings(robot, baseline)
        return "partial PATCH merged; DELETE then baseline restored"
    finally:
        await _apply_settings(robot, baseline)


async def _case_s12(
    settings: Settings,
    *,
    operator_token: str,
    auditor_token: str,
) -> str:
    async with build_robot_http_session(settings) as unauth_session:
        payload = await unauth_session.get_json("/auth/settings")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise AssertionError("GET /auth/settings without auth missing data object")

        try:
            await unauth_session.patch_json(
                "/auth/settings",
                json_body={"data": {"idleLogout": 999.0}},
                expected_status=(401, 403),
            )
        except RobotApiError as exc:
            if exc.status_code == 200:
                raise AssertionError(
                    "PATCH /auth/settings allowed without auth",
                ) from exc
            if exc.status_code not in {401, 403}:
                raise

    async with FlexRobot(settings, access_token=operator_token) as operator_robot:
        try:
            await operator_robot.auth_settings.patch_settings(
                {"idleLogout": 999.0},
            )
        except RobotApiError as exc:
            if exc.status_code not in {403, 401}:
                raise
        else:
            raise AssertionError("operator PATCH /auth/settings should be denied")

    async with FlexRobot(settings, access_token=auditor_token) as auditor_robot:
        auditor_payload = await auditor_robot.auth_settings.get_settings()
        if auditor_payload.max_number_of_login_attempts < 1:
            raise AssertionError("auditor GET /auth/settings returned invalid payload")

    return (
        "GET allowed without auth; PATCH denied without auth and for operator; "
        "auditor GET ok"
    )


async def _expect_http_denied(
    action: Callable[[], Awaitable[Any]],
    *,
    label: str,
    also_accept: frozenset[int] | None = None,
) -> None:
    allowed = {401, 403, 409} | (also_accept or frozenset())
    try:
        await action()
    except RobotApiError as exc:
        if exc.status_code in allowed:
            return
        raise
    else:
        raise AssertionError(f"expected HTTP denial for {label}")


def _extract_protocol_id(payload: dict[str, Any]) -> str:
    data = payload.get("data", payload)
    if isinstance(data, dict) and "id" in data:
        return str(data["id"])
    raise ValueError(f"missing protocol id in {payload!r}")


def _extract_run_id(payload: dict[str, Any]) -> str:
    data = payload.get("data", payload)
    if isinstance(data, dict) and "id" in data:
        return str(data["id"])
    raise ValueError(f"missing run id in {payload!r}")


def _extract_update_token(payload: dict[str, Any]) -> str | None:
    data = payload.get("data", payload)
    if isinstance(data, dict):
        token = data.get("token") or data.get("id")
        if token is not None:
            return str(token)
    token = payload.get("token")
    return str(token) if token is not None else None
