"""Compact robot status via typed clients (instruments, door, subsystems)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.robots.flex import FlexRobot

STATUS_DESCRIPTOR = CapabilityDescriptor(
    name="robot_status",
    description=(
        "Summarize health, instruments, door, and subsystems using typed "
        "clients (no ad-hoc URLs)."
    ),
    risk_level=RiskLevel.READ_ONLY,
    mutates_robot=False,
    evidence_produced=["robot_status.json"],
    preconditions=["ROBOT_HOST configured"],
)


class RobotStatusSummary(BaseModel):
    """Operator-facing status snapshot."""

    name: str | None = None
    host: str
    system_version: str | None = None
    api_version: str | None = None
    access_control_enabled: bool | None = None
    door: dict[str, Any] | None = None
    instruments: list[dict[str, Any]] = Field(default_factory=list)
    subsystems: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


async def robot_status(robot: FlexRobot) -> RobotStatusSummary:
    """Collect a compact status using FlexRobot clients only."""
    ensure_mutation_allowed(
        robot.settings,
        risk_level=STATUS_DESCRIPTOR.risk_level,
        capability_name=STATUS_DESCRIPTOR.name,
    )
    host = robot.settings.require_robot_host()
    errors: list[str] = []
    raw: dict[str, Any] = {}

    name: str | None = None
    system_version: str | None = None
    api_version: str | None = None
    try:
        health = await robot.verify_health()
        name = health.name
        system_version = health.system_version
        api_version = health.api_version
        raw["health"] = health.model_dump(mode="json")
    except Exception as exc:
        errors.append(f"health: {exc}")

    access_control_enabled: bool | None = None
    try:
        ac = await robot.auth_settings.detect_access_control(
            timeout=robot.settings.robot_request_timeout_seconds
        )
        access_control_enabled = ac.raw_enabled
        raw["access_control"] = ac.model_dump(mode="json")
    except Exception as exc:
        errors.append(f"access_control: {exc}")

    door: dict[str, Any] | None = None
    try:
        door = await robot.robot_control.get_door_status()
        raw["door"] = door
    except Exception as exc:
        errors.append(f"door: {exc}")

    instruments: list[dict[str, Any]] = []
    try:
        instruments = await robot.instruments.list_instrument_summaries()
        raw["instruments"] = instruments
    except Exception as exc:
        errors.append(f"instruments: {exc}")

    subsystems: list[dict[str, Any]] = []
    try:
        subsystems = await robot.subsystems.list_status()
        raw["subsystems"] = subsystems
    except Exception as exc:
        errors.append(f"subsystems: {exc}")

    summary = RobotStatusSummary(
        name=name,
        host=host,
        system_version=system_version,
        api_version=api_version,
        access_control_enabled=access_control_enabled,
        door=door,
        instruments=instruments,
        subsystems=subsystems,
        errors=errors,
        raw=raw,
    )
    robot.raw_evidence["robot_status"] = summary.model_dump(mode="json")
    return summary
