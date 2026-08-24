"""Resolve KansasFLEX when lab DHCP moves the robot IP."""

from __future__ import annotations

import ssl

import httpx

from flex_testing_agent.clients.auth_settings import AuthSettingsClient
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.access_control import AccessControlState
from flex_testing_agent.robot_certs.registry import RobotCertRegistryError
from flex_testing_agent.robot_certs.resolve import resolve_httpx_verify

log = get_logger(__name__)

OPENTRONS_VERSION_HEADER = "Opentrons-Version"
OPENTRONS_VERSION = "3"


class RobotDiscoveryError(RuntimeError):
    """Raised when no candidate robot host responds to ``GET /health``."""


class CrsHttpsRequiredError(RuntimeError):
    """CRS is on but the harness cannot use HTTPS (missing CA trust)."""


async def probe_robot_host(
    host: str,
    *,
    port: int,
    use_https: bool,
    timeout_seconds: float,
    expected_name: str | None = None,
    verify: bool | ssl.SSLContext = True,
) -> dict[str, object] | None:
    """Return ``/health`` JSON if the host looks like a reachable Flex."""
    scheme = "https" if use_https else "http"
    url = f"{scheme}://{host}:{port}/health"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, verify=verify) as client:
            response = await client.get(
                url,
                headers={OPENTRONS_VERSION_HEADER: OPENTRONS_VERSION},
            )
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if expected_name:
        name = payload.get("name")
        if isinstance(name, str) and name and name != expected_name:
            log.info(
                "robot_host_name_mismatch",
                host=host,
                expected=expected_name,
                actual=name,
            )
            return None
    return payload


def _bind_host(
    settings: Settings,
    host: str,
    *,
    use_https: bool | None = None,
) -> Settings:
    update: dict[str, object] = {}
    if host != settings.robot_host.strip():
        update["robot_host"] = host
    if use_https is not None and use_https != settings.robot_use_https:
        update["robot_use_https"] = use_https
    if not update:
        return settings
    return settings.model_copy(update=update)


async def resolve_robot_host(
    settings: Settings,
    *,
    use_https: bool | None = None,
) -> str:
    """Pick the first candidate host that answers ``GET /health``.

    Order: ``ROBOT_HOST`` (if set), then ``ROBOT_HOST_CANDIDATES``.
    When ``ROBOT_NAME`` is set (default KansasFLEX), prefer a matching
    ``health.name`` so we do not latch onto a different Flex on the LAN.

    ``use_https`` overrides ``settings.robot_use_https`` for the probe scheme.
    """
    candidates = settings.candidate_hosts()
    if not candidates:
        raise RobotDiscoveryError(
            "No robot hosts configured. Set ROBOT_HOST and/or "
            "ROBOT_HOST_CANDIDATES in the environment or .env file."
        )

    https = settings.robot_use_https if use_https is None else use_https
    expected_name = settings.robot_name.strip() or None
    timeout = min(settings.robot_health_timeout_seconds, 3.0)
    port = settings.robot_https_port if https else settings.robot_http_port
    verify_settings = (
        settings
        if https == settings.robot_use_https
        else settings.model_copy(update={"robot_use_https": True})
    )
    failures: list[str] = []

    for host in candidates:
        verify: bool | ssl.SSLContext = True
        if https:
            try:
                verify = resolve_httpx_verify(verify_settings, host=host)
            except Exception:
                failures.append(host)
                continue
        payload = await probe_robot_host(
            host,
            port=port,
            use_https=https,
            timeout_seconds=timeout,
            expected_name=expected_name,
            verify=verify,
        )
        if payload is None:
            failures.append(host)
            continue
        if host != settings.robot_host.strip():
            log.info(
                "robot_host_discovered",
                configured=settings.robot_host or None,
                resolved=host,
                robot_name=payload.get("name"),
                scheme="https" if https else "http",
            )
        return host

    scheme = "https" if https else "http"
    raise RobotDiscoveryError(
        "No reachable Flex at candidate hosts "
        f"{candidates} (tried {scheme}://…:{port}/health; failed={failures}). "
        "Update ROBOT_HOST / ROBOT_HOST_CANDIDATES after DHCP moves."
    )


async def _access_control_enabled(settings: Settings) -> bool:
    """Return True only when the robot reports accessControlEnabled."""
    verify: bool | ssl.SSLContext = True
    if settings.robot_use_https:
        verify = resolve_httpx_verify(settings, host=settings.require_robot_host())
    async with RobotHttpSession(
        settings.robot_base_url,
        timeout_seconds=min(settings.robot_health_timeout_seconds, 3.0),
        verify=verify,
    ) as session:
        status = await AuthSettingsClient(session).detect_access_control()
    return status.state == AccessControlState.ENABLED


def _require_crs_https(settings: Settings, host: str) -> Settings:
    https_settings = _bind_host(settings, host, use_https=True)
    try:
        resolve_httpx_verify(https_settings, host=host)
    except RobotCertRegistryError as exc:
        raise CrsHttpsRequiredError(
            "CRS / access control is enabled. The harness must use HTTPS "
            f"({https_settings.robot_base_url}). Run `flex-test crs trust-ca` "
            "(Robot Encryption Key) so a CA PEM exists, then retry. "
            "Plaintext HTTP is not used for CRS-on API calls."
        ) from exc
    return https_settings


async def settings_with_resolved_host(settings: Settings) -> Settings:
    """Bind ``robot_host`` and force HTTPS when CRS is on.

    CRS-off stays on HTTP unless ``ROBOT_USE_HTTPS`` is already true.
    CRS-on always returns HTTPS settings. If plaintext ``:31950`` still
    answers, that is a product leak; the harness continues on ``:32313``.
    """
    if settings.robot_use_https:
        host = await resolve_robot_host(settings, use_https=True)
        return _bind_host(settings, host, use_https=True)

    try:
        host = await resolve_robot_host(settings, use_https=False)
    except RobotDiscoveryError as http_exc:
        try:
            host = await resolve_robot_host(settings, use_https=True)
        except RobotDiscoveryError as https_exc:
            raise RobotDiscoveryError(
                f"{http_exc} Also tried HTTPS :{settings.robot_https_port}."
            ) from https_exc
        log.info("robot_discovered_https_only", host=host)
        return _bind_host(settings, host, use_https=True)

    bound = _bind_host(settings, host, use_https=False)
    if not await _access_control_enabled(bound):
        return bound
    log.warning(
        "crs_on_plaintext_http_reachable",
        host=host,
        http_port=settings.robot_http_port,
        https_port=settings.robot_https_port,
        detail=(
            "accessControlEnabled=true but the robot still served HTTP. "
            "Product should close plaintext :31950; harness uses HTTPS."
        ),
    )
    return _require_crs_https(bound, host)


def describe_crs_https_upgrade(
    original: Settings,
    resolved: Settings,
) -> str | None:
    """Operator note when discovery switched HTTP to HTTPS because CRS is on."""
    if resolved.robot_use_https and not original.robot_use_https:
        return (
            f"CRS is on; using HTTPS {resolved.robot_base_url}. "
            "Plaintext HTTP is not used for CRS-on API calls "
            "(even if :31950 still answers; RQA-5981)."
        )
    return None
