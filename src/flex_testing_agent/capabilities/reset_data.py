"""Clear robot-server persisted data (runs / protocols / offsets)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.settings_reset import (
    AUTHORIZED_KEYS,
    DEFAULT_DATA_RESET,
    SettingsResetClient,
)
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.timing import TimingSession
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

RESET_DATA_DESCRIPTOR = CapabilityDescriptor(
    name="reset_robot_data",
    description=(
        "POST /settings/reset for robot-server data (default: runsHistory). "
        "Does not clear SSH authorizedKeys unless explicitly requested."
    ),
    risk_level=RiskLevel.DISRUPTIVE,
    mutates_robot=True,
    evidence_produced=["settings_reset.json", "timing"],
    preconditions=["ALLOW_MUTATIONS=true"],
)


class ResetDataResult(BaseModel):
    """Outcome of a settings reset."""

    options: dict[str, bool] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    timing_path: str | None = None


async def reset_robot_data(
    robot: FlexRobot,
    *,
    option_ids: set[str] | frozenset[str] | None = None,
    include_authorized_keys: bool = False,
    timing: TimingSession | None = None,
) -> ResetDataResult:
    """Apply selected ``/settings/reset`` options.

    Default clears ``runsHistory`` (robot-server DB: runs, protocols, offsets).
    """
    ensure_mutation_allowed(
        robot.settings,
        risk_level=RESET_DATA_DESCRIPTOR.risk_level,
        capability_name=RESET_DATA_DESCRIPTOR.name,
    )
    selected = set(option_ids if option_ids is not None else DEFAULT_DATA_RESET)
    if include_authorized_keys:
        selected.add(AUTHORIZED_KEYS)
    elif AUTHORIZED_KEYS in selected:
        raise RuntimeError(
            "Refusing to clear authorizedKeys unless include_authorized_keys=True"
        )

    owns_timing = timing is None
    session = timing or TimingSession(
        label="reset-data",
        robot_host=robot.settings.robot_host,
    )
    client = SettingsResetClient(robot.session)
    async with session.aspan("reset.settings", meta={"options": sorted(selected)}):
        response = await client.reset_selected(selected)

    robot.raw_evidence["settings_reset"] = {
        "options": {oid: True for oid in sorted(selected)},
        "response": response,
    }
    path: str | None = None
    if owns_timing:
        written = session.write(robot.settings.ensure_artifact_directory() / "timing")
        path = str(written)
    log.info("reset_robot_data_complete", options=sorted(selected), timing=path)
    return ResetDataResult(
        options={oid: True for oid in sorted(selected)},
        response=response if isinstance(response, dict) else {},
        timing_path=path,
    )
