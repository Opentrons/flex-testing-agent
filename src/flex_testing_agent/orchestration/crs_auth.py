"""Shared OAuth helper for CRS-on robot sessions."""

from __future__ import annotations

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.robots.flex import FlexRobot


async def optional_access_token(
    settings: Settings,
    *,
    require_when_enabled: bool = False,
) -> str | None:
    """Return a bearer token when CRS is on and credentials are configured.

    Args:
        settings: Resolved robot settings.
        require_when_enabled: If True and CRS is on without credentials, raise.
    """
    async with FlexRobot(settings) as probe:
        raw = await probe.auth_settings.get_access_control_enabled_raw(
            timeout=settings.robot_health_timeout_seconds
        )
        data = raw.get("data", raw)
        enabled = isinstance(data, dict) and bool(data.get("accessControlEnabled"))
        if not enabled:
            return None
        username = settings.robot_username
        password = settings.robot_password
        if not username or not password:
            if require_when_enabled:
                raise RuntimeError(
                    "Access control is enabled; set ROBOT_USERNAME and "
                    "ROBOT_PASSWORD before this mutating or gated command."
                )
            return None
        token = await probe.oauth.get_token(username, password)
        return token.access_token
