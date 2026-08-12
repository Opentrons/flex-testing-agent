"""CRS-on authorization matrix (GET reachability with and without tokens)."""

from __future__ import annotations

from dataclasses import dataclass, field

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.catalog.crs_on_matrix import endpoints_for_crs_on_auth_matrix
from flex_testing_agent.catalog.endpoints import EndpointSpec
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.access_control import AccessControlState
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session

_MATRIX_USERS: tuple[tuple[str, str], ...] = (
    ("flex_test_operator", "user"),
    ("flex_test_auditor", "auditor"),
    ("flex_test_service", "service"),
    ("flex_harness_admin", "admin"),
)

_ALLOW_STATUSES = frozenset({200, 404})


@dataclass(frozen=True, slots=True)
class MatrixProbeResult:
    endpoint: str
    path: str
    actor: str
    account_type: str | None
    expected: str
    status_code: int | None
    ok: bool
    detail: str | None = None


@dataclass
class AuthMatrixResult:
    results: list[MatrixProbeResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for row in self.results if row.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for row in self.results if not row.ok)


async def _resolve_matrix_path(
    settings: Settings,
    template: str,
    *,
    access_token: str | None,
) -> str | None:
    """Resolve parameterized matrix paths using lab fixture IDs."""
    if "{username}" in template:
        return template.replace("{username}", "flex_test_admin")
    if "{runId}" in template:
        async with build_robot_http_session(
            settings,
            access_token=access_token,
        ) as session:
            try:
                payload = await session.get_json("/runs")
            except RobotApiError:
                return None
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if not data:
            return None
        run_id = data[0].get("id") if isinstance(data[0], dict) else None
        if not isinstance(run_id, str):
            return None
        return template.replace("{runId}", run_id)
    if "{" in template:
        return None
    return template


async def _probe_get(
    settings: Settings,
    path: str,
    *,
    access_token: str | None,
) -> int | None:
    async with build_robot_http_session(settings, access_token=access_token) as session:
        try:
            await session.get_json(path)
            return 200
        except RobotApiError as exc:
            return exc.status_code


async def run_auth_matrix(settings: Settings) -> AuthMatrixResult:
    """Verify catalogued GET endpoints work with and without OAuth tokens."""
    async with FlexRobot(settings) as robot:
        status = await robot.auth_settings.detect_access_control()
        if status.state != AccessControlState.ENABLED:
            raise RuntimeError(
                "CRS is not enabled; auth matrix requires accessControlEnabled=true"
            )

    endpoints = endpoints_for_crs_on_auth_matrix()
    result = AuthMatrixResult()
    token_cache: dict[str, str] = {}

    for spec in endpoints:
        await _run_endpoint_cases(settings, spec, result, token_cache)

    return result


async def _run_endpoint_cases(
    settings: Settings,
    spec: EndpointSpec,
    result: AuthMatrixResult,
    token_cache: dict[str, str],
) -> None:
    path = await _resolve_matrix_path(settings, spec.path, access_token=None)
    if path is None:
        result.skipped.append(f"{spec.name}: unresolved path {spec.path}")
        return

    # CRS access control applies to mutations only; GET must work with or
    # without credentials on all services.
    status = await _probe_get(settings, path, access_token=None)
    ok = status in _ALLOW_STATUSES if status is not None else False
    detail = None if ok else f"GET without token returned {status}"
    result.results.append(
        MatrixProbeResult(
            endpoint=spec.name,
            path=path,
            actor="(none)",
            account_type=None,
            expected="allow",
            status_code=status,
            ok=ok,
            detail=detail,
        )
    )

    for username, account_type in _MATRIX_USERS:
        if username not in token_cache:
            token_cache[username] = await access_token_for_username(settings, username)
        status = await _probe_get(
            settings,
            path,
            access_token=token_cache[username],
        )
        ok = status in _ALLOW_STATUSES if status is not None else False
        detail = None if ok else f"GET with token returned {status}"
        result.results.append(
            MatrixProbeResult(
                endpoint=spec.name,
                path=path,
                actor=username,
                account_type=account_type,
                expected="allow",
                status_code=status,
                ok=ok,
                detail=detail,
            )
        )
