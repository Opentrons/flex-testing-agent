"""Resolve KansasFLEX when lab DHCP moves the robot IP."""

from __future__ import annotations

import httpx

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.logging import get_logger

log = get_logger(__name__)

OPENTRONS_VERSION_HEADER = "Opentrons-Version"
OPENTRONS_VERSION = "3"


class RobotDiscoveryError(RuntimeError):
    """Raised when no candidate robot host responds to ``GET /health``."""


async def probe_robot_host(
    host: str,
    *,
    port: int,
    use_https: bool,
    timeout_seconds: float,
    expected_name: str | None = None,
) -> dict[str, object] | None:
    """Return ``/health`` JSON if the host looks like a reachable Flex."""
    scheme = "https" if use_https else "http"
    url = f"{scheme}://{host}:{port}/health"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
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


async def resolve_robot_host(settings: Settings) -> str:
    """Pick the first candidate host that answers ``GET /health``.

    Order: ``ROBOT_HOST`` (if set), then ``ROBOT_HOST_CANDIDATES``.
    When ``ROBOT_NAME`` is set (default KansasFLEX), prefer a matching
    ``health.name`` so we do not latch onto a different Flex on the LAN.
    """
    candidates = settings.candidate_hosts()
    if not candidates:
        raise RobotDiscoveryError(
            "No robot hosts configured. Set ROBOT_HOST and/or "
            "ROBOT_HOST_CANDIDATES in the environment or .env file."
        )

    expected_name = settings.robot_name.strip() or None
    timeout = min(settings.robot_health_timeout_seconds, 3.0)
    if settings.robot_use_https:
        port = settings.robot_https_port
    else:
        port = settings.robot_http_port
    failures: list[str] = []

    for host in candidates:
        payload = await probe_robot_host(
            host,
            port=port,
            use_https=settings.robot_use_https,
            timeout_seconds=timeout,
            expected_name=expected_name,
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
            )
        return host

    raise RobotDiscoveryError(
        "No reachable Flex at candidate hosts "
        f"{candidates} (tried /health; failed={failures}). "
        "Update ROBOT_HOST / ROBOT_HOST_CANDIDATES after DHCP moves."
    )


async def settings_with_resolved_host(settings: Settings) -> Settings:
    """Return a settings copy with ``robot_host`` bound to a live candidate."""
    host = await resolve_robot_host(settings)
    if host == settings.robot_host.strip():
        return settings
    return settings.model_copy(update={"robot_host": host})
