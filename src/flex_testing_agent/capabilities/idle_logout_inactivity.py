"""CRS-on idleLogout inactivity probe (no client refresh-token rotation)."""

from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel

from flex_testing_agent.capabilities.crs_auth import (
    access_token_for_username,
    ensure_crs_on,
)
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.robots.flex import FlexRobot

DEFAULT_MARGIN_AFTER_IDLE_LOGOUT_S = 5.0


IDLE_LOGOUT_INACTIVITY = CapabilityDescriptor(
    name="idle_logout_inactivity",
    description=(
        "Wait past idleLogout without authenticated API traffic on a single "
        "ROPC access token and expect introspection inactive. Authenticated "
        "API calls do not extend access-token lifetime; only client "
        "refresh-token grants do (Opentrons App implements refresh)."
    ),
    risk_level=RiskLevel.READ_ONLY,
    mutates_robot=False,
    requires_cleanup=False,
    evidence_produced=["idle_logout_inactivity.json"],
    preconditions=[
        "CRS / accessControlEnabled is true",
        "ROBOT_USE_HTTPS=true and CA trust configured",
        "Fixture user credentials configured",
        "idleLogout on the robot is short enough for the chosen wait, or pass "
        "--wait-seconds explicitly (settings-suite S6 PATCHes idleLogout to 60)",
    ],
)


class IdleLogoutInactivityResult(BaseModel):
    """Outcome of the idleLogout inactivity probe."""

    username: str
    idle_logout_seconds: float
    wait_seconds: float
    introspect_active_before: bool
    introspect_active_after: bool
    ok: bool
    detail: str = ""


def resolve_inactivity_wait(
    *,
    idle_logout_seconds: float,
    margin_seconds: float = DEFAULT_MARGIN_AFTER_IDLE_LOGOUT_S,
    wait_seconds: float | None = None,
) -> float:
    """Seconds to sleep with no API traffic before re-checking the token."""
    if wait_seconds is not None:
        return wait_seconds
    return idle_logout_seconds + margin_seconds


async def run_idle_logout_inactivity(
    settings: Settings,
    *,
    username: str = "flex_test_operator",
    margin_seconds: float = DEFAULT_MARGIN_AFTER_IDLE_LOGOUT_S,
    wait_seconds: float | None = None,
) -> IdleLogoutInactivityResult:
    """Wait without API calls, then expect the access token is inactive."""
    access_token = await access_token_for_username(settings, username)
    async with FlexRobot(settings, access_token=access_token) as robot:
        await ensure_crs_on(robot)
        auth_settings = await robot.auth_settings.get_settings()
        idle_logout = auth_settings.idle_logout
        total_wait = resolve_inactivity_wait(
            idle_logout_seconds=idle_logout,
            margin_seconds=margin_seconds,
            wait_seconds=wait_seconds,
        )

        before = await robot.oauth.introspect_token(access_token)
        if not before.active:
            return IdleLogoutInactivityResult(
                username=username,
                idle_logout_seconds=idle_logout,
                wait_seconds=0.0,
                introspect_active_before=False,
                introspect_active_after=False,
                ok=False,
                detail="token already inactive before idle wait",
            )

        started = time.monotonic()
        await asyncio.sleep(total_wait)
        elapsed = time.monotonic() - started

        after = await robot.oauth.introspect_token(access_token)
        ok = not after.active
        detail = (
            f"token inactive after {elapsed:.1f}s idle "
            f"(idleLogout={idle_logout}s, wait={total_wait}s)"
            if ok
            else (
                f"token still active after {elapsed:.1f}s idle "
                f"(idleLogout={idle_logout}s, wait={total_wait}s)"
            )
        )
        result = IdleLogoutInactivityResult(
            username=username,
            idle_logout_seconds=idle_logout,
            wait_seconds=total_wait,
            introspect_active_before=True,
            introspect_active_after=after.active,
            ok=ok,
            detail=detail,
        )
        robot.raw_evidence["idle_logout_inactivity"] = result.model_dump(mode="json")
        return result
