"""CRS-on lockdown negative auth suite (no / bad / under-scoped credentials)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.capabilities.crs_off import (
    DEFAULT_SMOKE_PROTOCOL,
    gather_tier_b_fixtures,
    resolve_tier_b_path,
)
from flex_testing_agent.catalog.crs_on_lockdown import (
    DENY_STATUSES,
    LEAK_STATUSES,
    auditor_should_deny,
    endpoints_for_crs_on_lockdown,
    is_mutation_method,
    is_public_when_crs_on,
    is_strict_lockdown_service,
    operator_should_deny,
    resolve_lockdown_path,
    unauthenticated_should_deny,
)
from flex_testing_agent.catalog.endpoints import EndpointSpec, HttpMethod
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.http_probe import HttpStatusProbe, probe_http_status
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.access_control import AccessControlState
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.run_state import DesiredRunState, ensure_run_state
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session

BAD_BEARER_TOKEN = "flex-testing-agent.invalid-bearer-token"
TOKEN_REFRESH_AFTER_S = 90.0
MALFORMED_BEARER_TOKEN = "not-a-jwt"
BAD_OAUTH_USERNAME = "flex_test_nonexistent_user"
BAD_OAUTH_PASSWORD = "wrong-password-not-valid"


class LockdownActor(StrEnum):
    """Negative auth personas for lockdown probes."""

    NONE = "none"
    BAD_BEARER = "bad_bearer"
    MALFORMED_BEARER = "malformed_bearer"
    BAD_OAUTH = "bad_oauth"
    AUDITOR = "auditor"
    OPERATOR = "operator"


@dataclass(frozen=True, slots=True)
class LockdownProbeResult:
    endpoint: str
    method: str
    path: str
    actor: str
    expected: str
    status_code: int | None
    ok: bool
    detail: str | None = None
    body_has_data: bool = False


@dataclass
class LockdownSuiteResult:
    results: list[LockdownProbeResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    oauth_bad_password_status: int | None = None
    oauth_bad_password_ok: bool | None = None
    label: str = "lockdown"
    fixtures: dict[str, Any] = field(default_factory=dict)

    @property
    def ok_count(self) -> int:
        return sum(1 for row in self.results if row.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for row in self.results if not row.ok)

    @property
    def leak_count(self) -> int:
        return sum(
            1
            for row in self.results
            if not row.ok and row.body_has_data and row.status_code in LEAK_STATUSES
        )

    def hard_failures(self) -> list[LockdownProbeResult]:
        """Rows that should block release (mutation bypass, strict-service gaps)."""
        out: list[LockdownProbeResult] = []
        for row in self.results:
            if row.ok:
                continue
            if row.body_has_data and row.status_code in LEAK_STATUSES:
                out.append(row)
                continue
            if row.actor == "plaintext_http":
                out.append(row)
                continue
            if (
                row.expected == "deny"
                and row.detail
                and "expected 401/403" in row.detail
            ):
                out.append(row)
        return out

    def write_evidence(self, settings: Settings) -> Path:
        """Persist JSON summary under artifacts/."""
        out_dir = settings.ensure_artifact_directory() / "pyro-tests"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"crs-on-lockdown-{self.label}.json"
        payload = {
            "label": self.label,
            "ok_count": self.ok_count,
            "fail_count": self.fail_count,
            "leak_count": self.leak_count,
            "oauth_bad_password_status": self.oauth_bad_password_status,
            "oauth_bad_password_ok": self.oauth_bad_password_ok,
            "skipped": self.skipped,
            "fixtures": self.fixtures,
            "hard_failures": [
                {
                    "endpoint": row.endpoint,
                    "method": row.method,
                    "path": row.path,
                    "actor": row.actor,
                    "expected": row.expected,
                    "status_code": row.status_code,
                    "detail": row.detail,
                    "body_has_data": row.body_has_data,
                }
                for row in self.hard_failures()
            ],
            "failures": [
                {
                    "endpoint": row.endpoint,
                    "method": row.method,
                    "path": row.path,
                    "actor": row.actor,
                    "expected": row.expected,
                    "status_code": row.status_code,
                    "detail": row.detail,
                    "body_has_data": row.body_has_data,
                }
                for row in self.results
                if not row.ok
            ],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path


def _expectation_for_actor(spec: EndpointSpec, actor: LockdownActor) -> str | None:
    """Return deny/public_ok, or None when this actor should not probe spec."""
    if actor == LockdownActor.NONE:
        return "deny" if unauthenticated_should_deny(spec) else "public_ok"
    if actor in {LockdownActor.BAD_BEARER, LockdownActor.MALFORMED_BEARER}:
        if spec.name == "post_oauth2_token":
            return None
        if is_public_when_crs_on(spec) or not is_mutation_method(spec):
            return "public_ok"
        return "deny"
    if actor == LockdownActor.BAD_OAUTH:
        return None
    if actor == LockdownActor.AUDITOR:
        if auditor_should_deny(spec):
            return "deny"
        return None
    if actor == LockdownActor.OPERATOR:
        if operator_should_deny(spec):
            return "deny"
        return None
    return None


def _evaluate_probe(
    spec: EndpointSpec,
    *,
    actor: LockdownActor,
    expected: str,
    probe: HttpStatusProbe,
    strict: bool,
) -> LockdownProbeResult:
    status = probe.status_code
    detail: str | None = None
    ok = False

    if status is None:
        return LockdownProbeResult(
            endpoint=spec.name,
            method=spec.method.value,
            path=spec.path,
            actor=actor.value,
            expected=expected,
            status_code=None,
            ok=False,
            detail="no response",
            body_has_data=probe.has_json_data,
        )

    if expected == "public_ok":
        ok = status < 500
    elif expected == "allow":
        ok = status in LEAK_STATUSES or status == 404
        if status in DENY_STATUSES:
            detail = "scoped user incorrectly denied"
            ok = False
    elif expected == "deny":
        if status in DENY_STATUSES:
            ok = True
        elif status in LEAK_STATUSES:
            ok = False
            detail = (
                "mutation allowed without valid credentials"
                if probe.has_json_data
                else "mutation bypass: success without valid credentials"
            )
        elif strict:
            ok = False
            detail = f"expected 401/403, got {status}"
        else:
            ok = status < 500
            detail = f"robot-server report-only: got {status}"
    else:
        detail = f"unknown expectation {expected}"

    return LockdownProbeResult(
        endpoint=spec.name,
        method=spec.method.value,
        path=spec.path,
        actor=actor.value,
        expected=expected,
        status_code=status,
        ok=ok,
        detail=detail,
        body_has_data=probe.has_json_data,
    )


async def _token_for_actor(settings: Settings, actor: LockdownActor) -> str | None:
    if actor == LockdownActor.NONE:
        return None
    if actor == LockdownActor.BAD_BEARER:
        return BAD_BEARER_TOKEN
    if actor == LockdownActor.MALFORMED_BEARER:
        return MALFORMED_BEARER_TOKEN
    if actor == LockdownActor.AUDITOR:
        return await access_token_for_username(settings, "flex_test_auditor")
    if actor == LockdownActor.OPERATOR:
        return await access_token_for_username(settings, "flex_test_operator")
    return None


def _request_body_for(spec: EndpointSpec) -> dict[str, Any] | None:
    if spec.method in {HttpMethod.GET, HttpMethod.DELETE, HttpMethod.HEAD}:
        return None
    if spec.name == "post_oauth2_token":
        return None
    return {"data": {}}


async def _resolve_actor_tokens(
    settings: Settings,
    actors: tuple[LockdownActor, ...],
) -> tuple[dict[LockdownActor, str | None], list[str]]:
    """Prefetch OAuth tokens; skip scoped actors when token fetch fails."""
    tokens: dict[LockdownActor, str | None] = {}
    skipped: list[str] = []
    for actor in actors:
        if actor in {
            LockdownActor.NONE,
            LockdownActor.BAD_BEARER,
            LockdownActor.MALFORMED_BEARER,
        }:
            tokens[actor] = await _token_for_actor(settings, actor)
            continue
        if actor == LockdownActor.BAD_OAUTH:
            continue
        try:
            tokens[actor] = await _token_for_actor(settings, actor)
        except RobotApiError as exc:
            skipped.append(f"{actor.value}: token fetch failed ({exc})")
            tokens[actor] = None
    return tokens, skipped


async def _probe_endpoint(
    settings: Settings,
    spec: EndpointSpec,
    *,
    actor: LockdownActor,
    resolved_path: str,
    access_token: str | None,
) -> LockdownProbeResult:
    expected = _expectation_for_actor(spec, actor)
    if expected is None:
        raise RuntimeError(f"actor {actor} should not reach _probe_endpoint")

    strict = is_strict_lockdown_service(spec)
    async with build_robot_http_session(settings, access_token=access_token) as session:
        if spec.name == "post_oauth2_token" and actor == LockdownActor.NONE:
            probe = await probe_http_status(
                session,
                spec.method.value,
                resolved_path,
                form={
                    "grant_type": "password",
                    "client_id": "opentrons_app",
                    "username": "",
                    "password": "",
                },
                timeout=spec.timeout_seconds,
            )
        else:
            probe = await probe_http_status(
                session,
                spec.method.value,
                resolved_path,
                json_body=_request_body_for(spec),
                timeout=spec.timeout_seconds,
            )
    return _evaluate_probe(
        spec,
        actor=actor,
        expected=expected,
        probe=probe,
        strict=strict,
    )


async def _probe_bad_oauth(settings: Settings) -> tuple[int | None, bool]:
    """Wrong ROPC password must not return 200 with an access_token."""
    async with build_robot_http_session(settings) as session:
        probe = await probe_http_status(
            session,
            "POST",
            "/auth/oauth2/token",
            form={
                "grant_type": "password",
                "client_id": "opentrons_app",
                "username": BAD_OAUTH_USERNAME,
                "password": BAD_OAUTH_PASSWORD,
            },
        )
    if probe.status_code in DENY_STATUSES:
        return probe.status_code, True
    if probe.status_code in LEAK_STATUSES and probe.has_json_data:
        return probe.status_code, False
    return probe.status_code, probe.status_code not in LEAK_STATUSES


def _plaintext_http_row(
    *,
    endpoint: str,
    method: str,
    path: str,
    status_code: int | None,
) -> LockdownProbeResult:
    """CRS-on plaintext :31950 must not serve the API (QA checklist §9)."""
    closed = status_code is None
    if closed:
        detail = "plaintext HTTP did not respond (expected)"
    else:
        detail = (
            f"plaintext HTTP still served status={status_code}; "
            "expected no API on :31950 when CRS is on"
        )
    return LockdownProbeResult(
        endpoint=endpoint,
        method=method,
        path=path,
        actor="plaintext_http",
        expected="deny",
        status_code=status_code,
        ok=closed,
        detail=detail,
    )


async def probe_plaintext_http_closed(
    settings: Settings,
) -> list[LockdownProbeResult]:
    """Fail if CRS-on robot still answers HTTP ``:31950``.

    Connection/TLS-level failure is a pass. Any HTTP status means the
    plaintext API is still open (including 401 on OAuth).
    """
    http_settings = settings.model_copy(update={"robot_use_https": False})
    timeout = min(settings.robot_health_timeout_seconds, 3.0)
    rows: list[LockdownProbeResult] = []
    async with RobotHttpSession(
        http_settings.robot_base_url,
        timeout_seconds=timeout,
    ) as session:
        try:
            await session.get_json("/health")
            health_status: int | None = 200
        except RobotApiError as exc:
            health_status = exc.status_code
        rows.append(
            _plaintext_http_row(
                endpoint="plaintext_http_health",
                method="GET",
                path="/health",
                status_code=health_status,
            )
        )
        try:
            await session.post_form(
                "/auth/oauth2/token",
                form={
                    "grant_type": "password",
                    "client_id": "opentrons_app",
                    "username": "flex_test_nonexistent_user",
                    "password": "not-a-real-password",
                },
            )
            oauth_status: int | None = 200
        except RobotApiError as exc:
            oauth_status = exc.status_code
        rows.append(
            _plaintext_http_row(
                endpoint="plaintext_http_oauth",
                method="POST",
                path="/auth/oauth2/token",
                status_code=oauth_status,
            )
        )
    return rows


async def run_crs_on_lockdown(
    settings: Settings,
    *,
    actors: tuple[LockdownActor, ...] = (
        LockdownActor.NONE,
        LockdownActor.BAD_BEARER,
        LockdownActor.MALFORMED_BEARER,
        LockdownActor.AUDITOR,
        LockdownActor.OPERATOR,
    ),
    include_parameterized: bool = False,
    strict_only: bool = False,
    create_fixtures: bool = False,
    protocol_path: Path | None = None,
    fixture_username: str = "flex_test_service",
    label: str = "lockdown",
) -> LockdownSuiteResult:
    """Probe catalogued endpoints with negative auth personas."""
    async with FlexRobot(settings) as robot:
        status = await robot.auth_settings.detect_access_control()
        if status.state != AccessControlState.ENABLED:
            raise RuntimeError(
                "CRS is not enabled; lockdown suite requires accessControlEnabled=true"
            )

    result = LockdownSuiteResult(label=label)
    result.results.extend(await probe_plaintext_http_closed(settings))
    try:
        actor_tokens, token_skipped = await _resolve_actor_tokens(settings, actors)
        result.skipped.extend(token_skipped)
        tokens_minted_at = time.monotonic()

        if LockdownActor.BAD_OAUTH in actors:
            oauth_status, oauth_ok = await _probe_bad_oauth(settings)
            result.oauth_bad_password_status = oauth_status
            result.oauth_bad_password_ok = oauth_ok

        tier_b_fixtures = None
        if include_parameterized and create_fixtures:
            ensure_mutation_allowed(
                settings,
                risk_level=RiskLevel.REVERSIBLE_MUTATION,
                capability_name="crs_on_lockdown_fixtures",
            )
            token = await access_token_for_username(settings, fixture_username)
            smoke = protocol_path or DEFAULT_SMOKE_PROTOCOL
            async with FlexRobot(settings, access_token=token) as robot:
                snap = await ensure_run_state(
                    robot,
                    DesiredRunState.CURRENT_IDLE,
                    ensure=True,
                    capability_name="crs_on_lockdown_run_state",
                )
                tier_b_fixtures = await gather_tier_b_fixtures(
                    robot,
                    create_if_missing=True,
                    protocol_path=smoke,
                    preferred_run_id=snap.current_run_id,
                    auth_username="flex_test_nonexistent_user",
                )
            result.fixtures = {
                key: value
                for key, value in tier_b_fixtures.__dict__.items()
                if key != "created" and value is not None
            }

        endpoints = endpoints_for_crs_on_lockdown(
            include_parameterized=include_parameterized,
        )

        for spec in endpoints:
            if time.monotonic() - tokens_minted_at >= TOKEN_REFRESH_AFTER_S:
                actor_tokens, token_skipped = await _resolve_actor_tokens(
                    settings, actors
                )
                result.skipped.extend(token_skipped)
                tokens_minted_at = time.monotonic()
            if strict_only and not is_strict_lockdown_service(spec):
                continue
            resolved: str | None
            if spec.parameterized and tier_b_fixtures is not None:
                resolved = resolve_tier_b_path(spec.path, tier_b_fixtures)
            elif is_public_when_crs_on(spec) and spec.name != "post_oauth2_token":
                resolved = resolve_lockdown_path(spec.path) or spec.path
            else:
                resolved = resolve_lockdown_path(spec.path)
            if resolved is None:
                result.skipped.append(f"{spec.name}: unresolved path {spec.path}")
                continue

            for actor in actors:
                if actor == LockdownActor.BAD_OAUTH:
                    continue
                if (
                    actor in {LockdownActor.AUDITOR, LockdownActor.OPERATOR}
                    and actor_tokens.get(actor) is None
                ):
                    continue
                expected = _expectation_for_actor(spec, actor)
                if expected is None:
                    continue
                row = await _probe_endpoint(
                    settings,
                    spec,
                    actor=actor,
                    resolved_path=resolved,
                    access_token=actor_tokens.get(actor),
                )
                result.results.append(row)
    finally:
        result.write_evidence(settings)

    return result
