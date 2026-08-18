"""Protocol-run presence preflight for harness suites.

Suites declare a desired :class:`DesiredRunState`, snapshot the robot, then either
verify-only (fail clearly) or ensure (mutate under ``ALLOW_MUTATIONS``).

See ``docs/crs-testing.md`` § Run state matrix.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)


class DesiredRunState(StrEnum):
    """Run presence targets that matter for CRS-off / camera suites."""

    ANY = "any"
    """Snapshot only; do not require a specific presence."""

    NO_CURRENT = "no-current"
    """No protocol run with ``current=true`` (camera picture / Tier A baseline)."""

    CURRENT_IDLE = "current-idle"
    """Exactly one current run in ``idle`` status (created, not played)."""


class RunStateSnapshot(BaseModel):
    """Observed protocol-run presence on the robot."""

    has_current: bool
    current_run_id: str | None = None
    current_status: str | None = None
    run_count: int = 0
    run_ids: list[str] = Field(default_factory=list)
    links_current_href: str | None = None

    def matches(self, desired: DesiredRunState) -> bool:
        """Return True if this snapshot satisfies ``desired``."""
        if desired is DesiredRunState.ANY:
            return True
        if desired is DesiredRunState.NO_CURRENT:
            return not self.has_current
        if desired is DesiredRunState.CURRENT_IDLE:
            return (
                self.has_current
                and self.current_run_id is not None
                and (self.current_status or "").lower() == "idle"
            )
        return False

    def describe(self) -> str:
        """Short operator-facing summary."""
        if not self.has_current:
            return f"no current run (run_count={self.run_count})"
        return (
            f"current={self.current_run_id} status={self.current_status} "
            f"(run_count={self.run_count})"
        )


class RunStateError(RuntimeError):
    """Robot run presence does not match the suite requirement."""


async def snapshot_run_state(robot: FlexRobot) -> RunStateSnapshot:
    """Read ``GET /runs`` and summarize current / history presence."""
    payload = await robot.runs.list_runs()
    data = payload.get("data")
    runs = data if isinstance(data, list) else []
    run_ids: list[str] = []
    current_id: str | None = None
    current_status: str | None = None
    for item in runs:
        if not isinstance(item, dict):
            continue
        rid = item.get("id")
        if rid is not None:
            run_ids.append(str(rid))
        if item.get("current") is True:
            current_id = str(rid) if rid is not None else current_id
            status = item.get("status")
            current_status = str(status) if status is not None else None

    links = payload.get("links")
    href: str | None = None
    if isinstance(links, dict):
        current_link = links.get("current")
        if isinstance(current_link, dict):
            raw_href = current_link.get("href")
            href = str(raw_href) if raw_href is not None else None
            if current_id is None and isinstance(raw_href, str):
                # links.current.href looks like /runs/{uuid}
                parts = raw_href.rstrip("/").split("/")
                if parts:
                    current_id = parts[-1]

    return RunStateSnapshot(
        has_current=current_id is not None,
        current_run_id=current_id,
        current_status=current_status,
        run_count=len(run_ids),
        run_ids=run_ids,
        links_current_href=href,
    )


async def release_current_run(
    robot: FlexRobot,
    run_id: str,
    *,
    signed_by: str | None = None,
) -> None:
    """Uncurrent a run; CRS-on requires stop + protocol-log signoff first."""
    if signed_by:
        status = (
            robot.runs.status_from_run(await robot.runs.get_run(run_id)) or ""
        ).lower()
        if status == "idle":
            await robot.runs.stop(run_id)
            for _ in range(20):
                await asyncio.sleep(0.25)
                status = (
                    robot.runs.status_from_run(await robot.runs.get_run(run_id)) or ""
                ).lower()
                if status != "idle":
                    break
        last_signoff: RobotApiError | None = None
        for _ in range(6):
            try:
                await robot.runs.sign_off(run_id, signed_by=signed_by)
                last_signoff = None
                break
            except RobotApiError as exc:
                if exc.status_code != 409:
                    raise
                last_signoff = exc
                await asyncio.sleep(0.5)
        if last_signoff is not None:
            raise last_signoff
    last_uncurrent: RobotApiError | None = None
    for _ in range(6):
        payload = await robot.runs.get_run(run_id)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(data, dict) and data.get("current") is not True:
            return
        try:
            await robot.runs.set_current(run_id, current=False)
            return
        except RobotApiError as exc:
            if exc.status_code != 409:
                raise
            last_uncurrent = exc
            await asyncio.sleep(0.5)
    if last_uncurrent is not None:
        raise last_uncurrent


async def _uncurrent_all(
    robot: FlexRobot,
    *,
    signed_by: str | None = None,
) -> list[str]:
    """Set ``current=false`` on every current run. Returns affected ids."""
    snap = await snapshot_run_state(robot)
    changed: list[str] = []
    if snap.current_run_id is None:
        return changed
    # Only one current run is expected, but loop defensively via list.
    for run in await robot.runs.list_run_summaries():
        if run.get("current") is True and run.get("id") is not None:
            run_id = str(run["id"])
            await release_current_run(robot, run_id, signed_by=signed_by)
            changed.append(run_id)
            log.info("run_state_uncurrented", run_id=run_id)
    return changed


async def _ensure_current_idle(
    robot: FlexRobot,
    *,
    protocol_id: str | None,
) -> str:
    """Create or reuse a current idle run. Returns run id."""
    snap = await snapshot_run_state(robot)
    if (
        snap.has_current
        and snap.current_run_id is not None
        and (snap.current_status or "").lower() == "idle"
    ):
        return snap.current_run_id

    if snap.has_current and snap.current_run_id is not None:
        # Current but not idle (running / succeeded / stopped-as-current): uncurrent
        # first so we can create a fresh idle current run.
        await robot.runs.set_current(snap.current_run_id, current=False)
        log.info("run_state_uncurrented_non_idle", run_id=snap.current_run_id)

    if protocol_id is None:
        protocols = await robot.protocols.list_protocol_summaries()
        if not protocols:
            raise RunStateError(
                "CURRENT_IDLE required but no protocol_id available to create a run. "
                "Upload a protocol or pass protocol_id / --create-fixtures."
            )
        protocol_id = str(protocols[0]["id"])

    created = await robot.runs.create_run(protocol_id=protocol_id)
    run_id = robot.runs.run_id_from_create(created)
    if run_id is None:
        raise RunStateError("POST /runs succeeded but run id missing")
    log.info("run_state_created_current_idle", run_id=run_id, protocol_id=protocol_id)
    return run_id


async def ensure_run_state(
    robot: FlexRobot,
    desired: DesiredRunState,
    *,
    ensure: bool = False,
    protocol_id: str | None = None,
    capability_name: str = "ensure_run_state",
    signed_by: str | None = None,
) -> RunStateSnapshot:
    """Snapshot, optionally mutate into ``desired``, then verify.

    Parameters
    ----------
    ensure:
        When True and the robot does not match, mutate under
        ``ALLOW_MUTATIONS`` (uncurrent and/or create idle run).
        When False, raise :class:`RunStateError` if mismatched
        (except ``DesiredRunState.ANY``).
    """
    before = await snapshot_run_state(robot)
    robot.raw_evidence["run_state_before"] = before.model_dump(mode="json")
    log.info(
        "run_state_snapshot",
        desired=desired.value,
        ensure=ensure,
        observed=before.describe(),
    )

    if before.matches(desired):
        robot.raw_evidence["run_state_after"] = before.model_dump(mode="json")
        return before

    if desired is DesiredRunState.ANY:
        robot.raw_evidence["run_state_after"] = before.model_dump(mode="json")
        return before

    if not ensure:
        raise RunStateError(
            f"Desired run state {desired.value!r} not met: {before.describe()}. "
            "Re-run with --ensure-run-state and ALLOW_MUTATIONS=true, or put the "
            "robot in the required state manually."
        )

    ensure_mutation_allowed(
        robot.settings,
        risk_level=RiskLevel.REVERSIBLE_MUTATION,
        capability_name=capability_name,
    )

    actions: dict[str, Any] = {"desired": desired.value}
    if desired is DesiredRunState.NO_CURRENT:
        actions["uncurrented"] = await _uncurrent_all(robot, signed_by=signed_by)
    elif desired is DesiredRunState.CURRENT_IDLE:
        actions["current_idle_run_id"] = await _ensure_current_idle(
            robot, protocol_id=protocol_id
        )
    robot.raw_evidence["run_state_actions"] = actions

    after = await snapshot_run_state(robot)
    robot.raw_evidence["run_state_after"] = after.model_dump(mode="json")
    if not after.matches(desired):
        raise RunStateError(
            f"Failed to reach run state {desired.value!r}: {after.describe()}"
        )
    log.info("run_state_ensured", desired=desired.value, observed=after.describe())
    return after


def parse_desired_run_state(value: str) -> DesiredRunState:
    """Parse CLI / config string into :class:`DesiredRunState`."""
    normalized = value.strip().lower().replace("_", "-")
    try:
        return DesiredRunState(normalized)
    except ValueError as exc:
        allowed = ", ".join(s.value for s in DesiredRunState)
        raise ValueError(
            f"Unknown run state {value!r}; expected one of: {allowed}"
        ) from exc
