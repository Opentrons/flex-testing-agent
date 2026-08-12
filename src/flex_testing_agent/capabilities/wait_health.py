"""Wait until robot-server ``/health`` (and optionally update-server) is ready."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.health import HealthReport, UpdateHealthReport
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

WAIT_HEALTH_DESCRIPTOR = CapabilityDescriptor(
    name="wait_for_health",
    description=(
        "Poll update-server and robot-server health until /health returns 200 "
        "(post-install / reboot recovery). Read-only; uses typed clients only."
    ),
    risk_level=RiskLevel.READ_ONLY,
    mutates_robot=False,
    max_execution_time_seconds=3600.0,
    evidence_produced=["wait_health.json"],
    preconditions=["ROBOT_HOST configured"],
)


class WaitHealthResult(BaseModel):
    """Outcome of waiting for robot HTTP health."""

    healthy: bool
    elapsed_seconds: float
    system_version: str | None = None
    api_version: str | None = None
    update_system_version: str | None = None
    health: HealthReport | None = None
    update_health: UpdateHealthReport | None = None
    last_error: str | None = None
    polls: int = 0
    detail: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


async def wait_for_health(
    robot: FlexRobot,
    *,
    timeout_seconds: float = 900.0,
    poll_interval_seconds: float = 5.0,
) -> WaitHealthResult:
    """Poll until ``GET /health`` succeeds (or timeout).

    While waiting, also samples ``GET /server/update/health`` when reachable
    (often reports the new OS version while robot-server is still 502).
    """
    ensure_mutation_allowed(
        robot.settings,
        risk_level=WAIT_HEALTH_DESCRIPTOR.risk_level,
        capability_name=WAIT_HEALTH_DESCRIPTOR.name,
    )
    robot.settings.require_robot_host()
    settings = robot.settings
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    started = asyncio.get_running_loop().time()
    last_error = "not reached"
    polls = 0
    update_report: UpdateHealthReport | None = None
    update_raw: dict[str, Any] | None = None

    while asyncio.get_running_loop().time() < deadline:
        polls += 1
        try:
            update_raw = await robot.update_health.get_update_health_raw(
                timeout=settings.robot_health_timeout_seconds
            )
            update_report = UpdateHealthReport.model_validate(update_raw)
        except Exception as exc:
            last_error = f"update_health: {exc}"
            log.info("wait_health_poll", error=last_error, poll=polls)

        try:
            raw = await robot.health.get_health_raw(
                timeout=settings.robot_health_timeout_seconds
            )
        except RobotApiError as exc:
            last_error = str(exc)
            log.info("wait_health_poll", error=last_error, poll=polls)
            await asyncio.sleep(poll_interval_seconds)
            continue
        except Exception as exc:
            last_error = str(exc)
            log.info("wait_health_poll", error=last_error, poll=polls)
            await asyncio.sleep(poll_interval_seconds)
            continue

        health = HealthReport.model_validate(raw)
        elapsed = asyncio.get_running_loop().time() - started
        result = WaitHealthResult(
            healthy=True,
            elapsed_seconds=elapsed,
            system_version=health.system_version,
            api_version=health.api_version,
            update_system_version=(
                update_report.system_version if update_report is not None else None
            ),
            health=health,
            update_health=update_report,
            polls=polls,
            detail="GET /health returned 200",
            raw={
                "health": raw,
                "update_health": update_raw,
            },
        )
        robot.raw_evidence["wait_health"] = result.model_dump(mode="json")
        return result

    elapsed = asyncio.get_running_loop().time() - started
    result = WaitHealthResult(
        healthy=False,
        elapsed_seconds=elapsed,
        update_system_version=(
            update_report.system_version if update_report is not None else None
        ),
        update_health=update_report,
        last_error=last_error,
        polls=polls,
        detail=f"Timed out after {timeout_seconds}s ({last_error})",
        raw={"update_health": update_raw},
    )
    robot.raw_evidence["wait_health"] = result.model_dump(mode="json")
    return result
