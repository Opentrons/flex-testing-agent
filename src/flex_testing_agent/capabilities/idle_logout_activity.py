"""CRS-on idleLogout activity test: token stays valid while API calls continue."""

from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.crs_auth import (
    access_token_for_username,
    ensure_crs_on,
)
from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.robots.flex import FlexRobot

DEFAULT_ACTIVITY_INTERVAL_S = 30.0
DEFAULT_MARGIN_AFTER_IDLE_LOGOUT_S = 30.0
MIN_ACTIVITY_INTERVAL_S = 5.0


IDLE_LOGOUT_ACTIVITY = CapabilityDescriptor(
    name="idle_logout_activity",
    description=(
        "Hold a single OAuth access token and issue authenticated API calls "
        "through the configured idleLogout window to verify activity refreshes "
        "the session."
    ),
    risk_level=RiskLevel.READ_ONLY,
    mutates_robot=False,
    requires_cleanup=False,
    evidence_produced=["idle_logout_activity.json"],
    preconditions=[
        "CRS / accessControlEnabled is true",
        "ROBOT_USE_HTTPS=true and CA trust configured",
        "Fixture user credentials configured",
    ],
)


class IdleLogoutActivityPing(BaseModel):
    """One activity probe during the idleLogout window."""

    elapsed_seconds: float
    introspect_active: bool
    self_get_ok: bool
    detail: str = ""


class IdleLogoutActivityResult(BaseModel):
    """Outcome of the idleLogout activity test."""

    username: str
    idle_logout_seconds: float
    duration_seconds: float
    activity_interval_seconds: float
    pings: list[IdleLogoutActivityPing] = Field(default_factory=list)
    ok: bool
    detail: str = ""


def resolve_activity_duration(
    *,
    idle_logout_seconds: float,
    margin_seconds: float = DEFAULT_MARGIN_AFTER_IDLE_LOGOUT_S,
    duration_seconds: float | None = None,
) -> float:
    """Seconds to keep the same token active past idleLogout."""
    if duration_seconds is not None:
        return duration_seconds
    return idle_logout_seconds + margin_seconds


async def run_idle_logout_activity(
    settings: Settings,
    *,
    username: str = "flex_test_operator",
    activity_interval_seconds: float = DEFAULT_ACTIVITY_INTERVAL_S,
    margin_seconds: float = DEFAULT_MARGIN_AFTER_IDLE_LOGOUT_S,
    duration_seconds: float | None = None,
) -> IdleLogoutActivityResult:
    """Keep one token and ping authenticated endpoints through idleLogout."""
    if activity_interval_seconds < MIN_ACTIVITY_INTERVAL_S:
        raise ValueError(
            f"activity_interval_seconds must be >= {MIN_ACTIVITY_INTERVAL_S}"
        )

    access_token = await access_token_for_username(settings, username)
    async with FlexRobot(settings, access_token=access_token) as robot:
        await ensure_crs_on(robot)
        auth_settings = await robot.auth_settings.get_settings()
        idle_logout = auth_settings.idle_logout
        total_duration = resolve_activity_duration(
            idle_logout_seconds=idle_logout,
            margin_seconds=margin_seconds,
            duration_seconds=duration_seconds,
        )

        started = time.monotonic()
        pings: list[IdleLogoutActivityPing] = []
        failure_detail = ""

        while True:
            elapsed = time.monotonic() - started
            if elapsed >= total_duration:
                break

            ping = await _activity_ping(
                robot,
                access_token=access_token,
                elapsed_seconds=elapsed,
            )
            pings.append(ping)
            if not ping.introspect_active or not ping.self_get_ok:
                failure_detail = (
                    f"token invalidated at {elapsed:.1f}s while active "
                    f"(idleLogout={idle_logout}s, detail={ping.detail})"
                )
                break

            remaining = total_duration - elapsed
            sleep_for = min(activity_interval_seconds, remaining)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

        if not failure_detail:
            final_elapsed = time.monotonic() - started
            final_ping = await _activity_ping(
                robot,
                access_token=access_token,
                elapsed_seconds=final_elapsed,
            )
            pings.append(final_ping)
            if not final_ping.introspect_active or not final_ping.self_get_ok:
                failure_detail = (
                    f"token invalidated after {final_elapsed:.1f}s active use "
                    f"(idleLogout={idle_logout}s, detail={final_ping.detail})"
                )

        ok = not failure_detail
        detail = failure_detail or (
            f"token remained active for {total_duration:.0f}s with "
            f"{len(pings)} activity pings (idleLogout={idle_logout}s)"
        )
        result = IdleLogoutActivityResult(
            username=username,
            idle_logout_seconds=idle_logout,
            duration_seconds=total_duration,
            activity_interval_seconds=activity_interval_seconds,
            pings=pings,
            ok=ok,
            detail=detail,
        )
        robot.raw_evidence["idle_logout_activity"] = result.model_dump(mode="json")
        return result


async def _activity_ping(
    robot: FlexRobot,
    *,
    access_token: str,
    elapsed_seconds: float,
) -> IdleLogoutActivityPing:
    """Authenticated GET /auth/users/self plus token introspection."""
    introspect_active = False
    self_get_ok = False
    detail_parts: list[str] = []

    intro = await robot.oauth.introspect_token(access_token)
    introspect_active = intro.active
    if not introspect_active:
        detail_parts.append("introspect active=false")

    try:
        await robot.users.get_self(access_token=access_token)
        self_get_ok = True
    except RobotApiError as exc:
        detail_parts.append(f"GET /auth/users/self HTTP {exc.status_code}")
    except Exception as exc:  # pragma: no cover - defensive
        detail_parts.append(f"GET /auth/users/self error: {exc}")

    return IdleLogoutActivityPing(
        elapsed_seconds=round(elapsed_seconds, 1),
        introspect_active=introspect_active,
        self_get_ok=self_get_ok,
        detail="; ".join(detail_parts),
    )


def format_ping_table_rows(
    pings: list[IdleLogoutActivityPing],
) -> list[tuple[str, str, str, str]]:
    """Rows for Rich table rendering in CLI."""
    rows: list[tuple[str, str, str, str]] = []
    for ping in pings:
        rows.append(
            (
                f"{ping.elapsed_seconds:.1f}s",
                "yes" if ping.introspect_active else "no",
                "yes" if ping.self_get_ok else "no",
                ping.detail[:80],
            )
        )
    return rows
