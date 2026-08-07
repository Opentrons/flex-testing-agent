"""Diagnostic robot logs client (``GET /logs/{log_identifier}``).

Source: robot-server legacy logs router. Identifiers are typically advertised
on ``GET /health`` as ``logs`` paths and ``links.apiLog`` / ``serialLog`` /
``serverLog``.
"""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.session import RobotHttpSession

# Stable defaults when /health omits log advertisements.
DEFAULT_LOG_IDENTIFIERS: tuple[str, ...] = ("api.log", "serial.log", "server.log")

_LINK_LOG_KEYS: tuple[str, ...] = ("apiLog", "serialLog", "serverLog")


def identifier_from_log_path(path: str) -> str | None:
    """Extract ``api.log`` from ``/logs/api.log`` (or return bare identifiers)."""
    text = path.strip()
    if not text:
        return None
    if text.startswith("/logs/"):
        ident = text[len("/logs/") :].strip("/")
        return ident or None
    if "/" in text:
        # Unexpected absolute path; take the basename.
        return text.rsplit("/", 1)[-1] or None
    return text


def discover_log_identifiers(
    health_payload: dict[str, Any],
    *,
    include_defaults: bool = True,
) -> list[str]:
    """Collect unique log identifiers from a ``/health`` JSON payload."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        ident = identifier_from_log_path(raw)
        if ident is None or ident in seen:
            return
        seen.add(ident)
        found.append(ident)

    logs = health_payload.get("logs")
    if isinstance(logs, list):
        for item in logs:
            if isinstance(item, str):
                _add(item)

    links = health_payload.get("links")
    if isinstance(links, dict):
        for key in _LINK_LOG_KEYS:
            value = links.get(key)
            if isinstance(value, str):
                _add(value)
        for key, value in links.items():
            if key in _LINK_LOG_KEYS:
                continue
            if isinstance(key, str) and key.endswith("Log") and isinstance(value, str):
                _add(value)

    if include_defaults:
        for ident in DEFAULT_LOG_IDENTIFIERS:
            _add(ident)

    return found


def normalize_log_identifier(log_identifier: str) -> str:
    """Normalize ``/logs/api.log`` or ``logs/api.log`` to ``api.log``."""
    ident = log_identifier.strip().lstrip("/")
    if ident.startswith("logs/"):
        ident = ident[len("logs/") :]
    return ident


class LogsClient:
    """Atomic client for Flex diagnostic log downloads."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def list_identifiers(
        self,
        *,
        timeout: float | None = None,
        include_defaults: bool = True,
    ) -> list[str]:
        """Discover log identifiers via ``GET /health``."""
        payload = await self._session.get_json("/health", timeout=timeout)
        return discover_log_identifiers(payload, include_defaults=include_defaults)

    async def get_log(
        self,
        log_identifier: str,
        *,
        timeout: float | None = None,
    ) -> tuple[bytes, str | None]:
        """Download ``GET /logs/{log_identifier}``; raise on non-2xx."""
        ident = normalize_log_identifier(log_identifier)
        path = f"/logs/{ident}"
        return await self._session.get_bytes(
            path, timeout=timeout, expected_status=(200,)
        )

    async def try_get_log(
        self,
        log_identifier: str,
        *,
        timeout: float | None = None,
    ) -> tuple[int, bytes | None, str | None]:
        """Download a log; ``404`` returns ``(404, None, None)`` without raising."""
        try:
            content, content_type = await self.get_log(log_identifier, timeout=timeout)
        except RobotApiError as exc:
            if exc.status_code == 404:
                return 404, None, None
            raise
        return 200, content, content_type
