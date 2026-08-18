"""CRS-on lockdown (negative auth) endpoint selection and expectations."""

from __future__ import annotations

from flex_testing_agent.catalog.crs_on_matrix import (
    account_has_required_scopes,
)
from flex_testing_agent.catalog.endpoints import (
    FLEX_HTTP_ENDPOINTS,
    ApiService,
    EndpointSpec,
    HttpMethod,
)
from flex_testing_agent.models.risk import RiskLevel

# Status codes that mean the caller was rejected before accessing protected data.
DENY_STATUSES: frozenset[int] = frozenset({401, 403})

# Successful HTTP responses for routes that do not require credentials (GET) or
# for authenticated callers that passed scope checks.
LEAK_STATUSES: frozenset[int] = frozenset({200, 201, 204})

# Mutating methods covered by CRS access control (POST, PATCH, PUT, DELETE).
_MUTATION_METHODS: frozenset[HttpMethod] = frozenset(
    {
        HttpMethod.POST,
        HttpMethod.PUT,
        HttpMethod.PATCH,
        HttpMethod.DELETE,
    }
)

# Endpoints intentionally reachable without a bearer token when CRS is on.
# ``post_oauth2_token`` is probed separately (bad credentials must not mint tokens).
# ``/clientData`` is App/ODD in-memory coordination, not under CRS (RQA-5918
# closed as expected: PUT/DELETE succeed with no token).
PUBLIC_WHEN_CRS_ON: frozenset[str] = frozenset(
    {
        "get_health",
        "get_server_update_health",
        "get_auth_settings_accessControlEnabled",
        "post_oauth2_token",
        "get_clientData_key",
        "put_clientData_key",
        "delete_clientData_key",
        "delete_clientData",
    }
)

# Placeholder path params for auth-only probes (resource may not exist).
LOCKDOWN_PLACEHOLDER_PARAMS: dict[str, str] = {
    "protocolId": "00000000-0000-4000-8000-000000000001",
    "analysisId": "00000000-0000-4000-8000-000000000002",
    "runId": "00000000-0000-4000-8000-000000000003",
    "commandId": "00000000-0000-4000-8000-000000000004",
    "dataFileId": "00000000-0000-4000-8000-000000000005",
    "cameraId": "ot_system_camera",
    "key": "flex-testing-agent-lockdown",
    "log_identifier": "api.log",
    "logPeriodId": "1",
    "subsystem": "gantry",
    "id": "flex-testing-agent-subsystem-update",
    "pipette_id": "flex-testing-agent-pipette",
    "username": "flex_test_nonexistent_user",
    "commandAnnotationId": "flex-testing-agent-annotation",
    "calibrationId": "flex-testing-agent-calibration",
    "session": "flex-testing-agent-update-session",
}

# Never live-probe these even for negative auth (side effects / reboot / wipe).
LOCKDOWN_EXCLUDED_NAMES: frozenset[str] = frozenset(
    {
        "post_server_restart",
        "post_server_shutdown",
        "post_settings_reset",
        "patch_auth_settings_accessControlEnabled",
    }
)

# DISRUPTIVE+ routes can reboot, wipe, or reconfigure the robot when authed.
LOCKDOWN_UNSAFE_RISK_LEVELS: frozenset[RiskLevel] = frozenset(
    {
        RiskLevel.DISRUPTIVE,
        RiskLevel.INSTALLATION,
        RiskLevel.DESTRUCTIVE,
    }
)


def is_lockdown_probe_safe(spec: EndpointSpec) -> bool:
    """Return False when probing could mutate robot state (lockdown is auth-only)."""
    if spec.blocked:
        return False
    if spec.name in LOCKDOWN_EXCLUDED_NAMES:
        return False
    if "redoc" in spec.path:
        return False
    return spec.risk_level not in LOCKDOWN_UNSAFE_RISK_LEVELS


def is_mutation_method(spec: EndpointSpec) -> bool:
    """Return True for HTTP methods covered by CRS access control."""
    return spec.method in _MUTATION_METHODS


def is_strict_lockdown_service(spec: EndpointSpec) -> bool:
    """Auth/audit mutations hard-fail when unauthenticated access is not denied."""
    return spec.service in (ApiService.AUTH_SERVER, ApiService.AUDIT_SERVER)


def endpoints_for_crs_on_lockdown(
    *,
    include_parameterized: bool = False,
) -> tuple[EndpointSpec, ...]:
    """Catalog entries for CRS-on negative auth (no / bad / under-scoped creds)."""
    out: list[EndpointSpec] = []
    for ep in FLEX_HTTP_ENDPOINTS:
        if not is_lockdown_probe_safe(ep):
            continue
        if ep.parameterized and not include_parameterized:
            continue
        out.append(ep)
    return tuple(out)


def resolve_lockdown_path(template: str) -> str | None:
    """Resolve ``{param}`` placeholders with stable fake IDs for auth probes."""
    path = template
    for key, value in LOCKDOWN_PLACEHOLDER_PARAMS.items():
        token = "{" + key + "}"
        if token in path:
            path = path.replace(token, value)
    if "{" in path:
        return None
    return path


def is_public_when_crs_on(spec: EndpointSpec) -> bool:
    """Return True when the endpoint may legitimately respond without OAuth."""
    return spec.name in PUBLIC_WHEN_CRS_ON


def unauthenticated_should_deny(spec: EndpointSpec) -> bool:
    """Whether an unauthenticated caller should be rejected (mutations only)."""
    if is_public_when_crs_on(spec):
        return False
    return is_mutation_method(spec)


def auditor_should_deny(spec: EndpointSpec) -> bool:
    """Auditor must not perform mutating requests outside their scopes."""
    if is_public_when_crs_on(spec):
        return False
    if spec.method == HttpMethod.GET:
        return False
    if not spec.required_scopes:
        return True
    return not account_has_required_scopes("auditor", spec.required_scopes)


def operator_should_deny(spec: EndpointSpec) -> bool:
    """Operator must not perform mutating requests outside user-role scopes."""
    if is_public_when_crs_on(spec):
        return False
    if spec.method == HttpMethod.GET:
        return False
    if not spec.required_scopes:
        return False
    return not account_has_required_scopes("user", spec.required_scopes)
