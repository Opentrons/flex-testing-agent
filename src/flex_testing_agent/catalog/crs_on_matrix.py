"""CRS-on authorization matrix case selection."""

from __future__ import annotations

from flex_testing_agent.catalog.endpoints import (
    FLEX_HTTP_ENDPOINTS,
    EndpointSpec,
    HttpMethod,
)


def endpoints_for_crs_on_auth_matrix() -> tuple[EndpointSpec, ...]:
    """GET endpoints with ``required_scopes`` suitable for CRS-on matrix probes."""
    return tuple(
        ep
        for ep in FLEX_HTTP_ENDPOINTS
        if ep.method == HttpMethod.GET and ep.required_scopes and not ep.blocked
    )


# Scope sets by account type (mirrors auth-server ``ACCOUNT_TYPE_TO_SCOPES``).
# Used for mutation lockdown expectations; GET routes are not CRS-gated.
ACCOUNT_SCOPE_NAMES: dict[str, frozenset[str]] = {
    "admin": frozenset(
        {
            "auth_settings.write",
            "protocols.write",
            "restart.write",
            "shutdown.write",
            "robot_control.write",
            "robot_settings.write",
            "run_data.write",
            "ssh_keys.write",
            "updates.write",
            "users.read.others",
            "users.read.self",
            "users.write.self",
            "users.write",
        }
    ),
    "service": frozenset(
        {
            "auth_settings.write",
            "protocols.write",
            "restart.write",
            "shutdown.write",
            "robot_control.write",
            "robot_settings.write",
            "run_data.write",
            "ssh_keys.write",
            "updates.write",
            "users.read.others",
            "users.read.self",
            "users.write.self",
            "users.write",
        }
    ),
    "user": frozenset(
        {
            "restart.write",
            "robot_control.write",
            "robot_settings.write",
            "updates.write",
            "users.read.self",
            "users.write.self",
            "protocols.write",
        }
    ),
    "auditor": frozenset({"users.read.others"}),
}


def account_has_required_scopes(
    account_type: str,
    required_scopes: tuple[str, ...],
) -> bool:
    """Return True when *account_type* grants all *required_scopes* (AND semantics)."""
    granted = ACCOUNT_SCOPE_NAMES.get(account_type, frozenset())
    return all(scope in granted for scope in required_scopes)
