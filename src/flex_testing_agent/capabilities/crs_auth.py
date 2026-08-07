"""Shared CRS-on OAuth helpers (avoids import cycles between probe and suites)."""

from __future__ import annotations

from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.crs_users import resolve_user_password
from flex_testing_agent.models.access_control import AccessControlState
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session


async def access_token_for_username(
    settings: Settings,
    username: str,
) -> str:
    """ROPC token for a fixture or bootstrap admin user."""
    password = resolve_user_password(username, settings=settings)
    if not password:
        raise ValueError(
            f"No password for user {username!r}; check crs_users.yaml or .env"
        )
    async with build_robot_http_session(settings) as session:
        token = await OAuthClient(session).get_token(username, password)
    return token.access_token


async def ensure_crs_on(robot: FlexRobot) -> None:
    """Fail fast when access control is not enabled."""
    status = await robot.auth_settings.detect_access_control()
    if status.state != AccessControlState.ENABLED:
        raise RuntimeError(
            "CRS / access control is not enabled; use flex-test probe for CRS-off. "
            f"state={status.state.value}"
        )
