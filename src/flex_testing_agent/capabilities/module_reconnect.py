"""Suite B: temperature-module USB reconnect regression checks."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.modules import ModulesClient, ModulesInventory
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

Phase = Literal[
    "b1",
    "wait-absent",
    "wait-present",
    "status",
    "smoke",
]

MODULE_RECONNECT_DESCRIPTOR = CapabilityDescriptor(
    name="module_reconnect_suite_b",
    description=(
        "Temperature-module USB reconnect checks for 9.1.2 "
        "(unique inventory, absent/present polling, smoke command)."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    mutates_robot=True,
    requires_cleanup=True,
    max_execution_time_seconds=300.0,
    required_robot_features=["temperature_module"],
    evidence_produced=["module_reconnect.json"],
)


class PhaseResult(BaseModel):
    """Outcome of one suite-B phase."""

    phase: str
    passed: bool
    detail: str
    inventory: dict[str, Any] | None = None
    elapsed_seconds: float | None = None
    command: dict[str, Any] | None = None


class SuiteBReport(BaseModel):
    """Aggregate report for suite B phases run in this session."""

    serial: str | None = None
    module_id: str | None = None
    results: list[PhaseResult] = Field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)


def _inventory_summary(inventory: ModulesInventory) -> dict[str, Any]:
    return {
        "count": inventory.count,
        "duplicate_serials": inventory.duplicate_serials(),
        "modules": [
            {
                "id": m.id,
                "serialNumber": m.serial_number,
                "moduleModel": m.module_model,
                "status": m.status,
                "currentTemperature": m.current_temperature,
                "usbPort": m.usb_port,
            }
            for m in inventory.modules
        ],
    }


async def run_suite_b_phase(
    robot: FlexRobot,
    phase: Phase,
    *,
    serial: str | None = None,
    timeout_seconds: float = 120.0,
    smoke_celsius: float = 25.0,
) -> PhaseResult:
    """Run one suite-B phase against the attached temperature module."""
    client = ModulesClient(robot.session)
    started = time.monotonic()

    if phase == "status":
        inventory = await client.list_modules()
        temps = inventory.temperature_modules()
        detail = (
            f"{inventory.count} module(s); "
            f"{len(temps)} temperature; "
            f"duplicates={inventory.duplicate_serials() or 'none'}"
        )
        result = PhaseResult(
            phase=phase,
            passed=True,
            detail=detail,
            inventory=_inventory_summary(inventory),
            elapsed_seconds=time.monotonic() - started,
        )
        robot.raw_evidence["module_reconnect_status"] = result.model_dump(mode="json")
        return result

    if phase == "b1":
        inventory = await client.list_modules()
        temps = inventory.temperature_modules()
        duplicates = inventory.duplicate_serials()
        ok = len(temps) == 1 and not duplicates
        target = temps[0] if temps else None
        if serial and target and target.serial_number != serial:
            ok = False
        detail = (
            f"temperature modules={len(temps)} "
            f"serials={[m.serial_number for m in temps]} "
            f"duplicates={duplicates or 'none'}"
        )
        result = PhaseResult(
            phase=phase,
            passed=ok,
            detail=detail,
            inventory=_inventory_summary(inventory),
            elapsed_seconds=time.monotonic() - started,
        )
        robot.raw_evidence["module_reconnect_b1"] = result.model_dump(mode="json")
        return result

    if phase == "wait-absent":
        if not serial:
            raise ValueError("wait-absent requires --serial")
        inventory = await client.wait_for(
            mode="absent",
            serial=serial,
            timeout_seconds=timeout_seconds,
        )
        result = PhaseResult(
            phase=phase,
            passed=True,
            detail=f"serial {serial} absent from inventory",
            inventory=_inventory_summary(inventory),
            elapsed_seconds=time.monotonic() - started,
        )
        robot.raw_evidence["module_reconnect_absent"] = result.model_dump(mode="json")
        return result

    if phase == "wait-present":
        if not serial:
            raise ValueError("wait-present requires --serial")
        inventory = await client.wait_for(
            mode="unique",
            serial=serial,
            timeout_seconds=timeout_seconds,
        )
        matches = inventory.by_serial(serial)
        ok = len(matches) == 1 and not inventory.duplicate_serials()
        mod = matches[0] if matches else None
        detail = (
            f"serial {serial} present once; "
            f"id={mod.id if mod else None}; "
            f"status={mod.status if mod else None}; "
            f"temp={mod.current_temperature if mod else None}"
        )
        result = PhaseResult(
            phase=phase,
            passed=ok,
            detail=detail,
            inventory=_inventory_summary(inventory),
            elapsed_seconds=time.monotonic() - started,
        )
        robot.raw_evidence["module_reconnect_present"] = result.model_dump(mode="json")
        return result

    if phase == "smoke":
        ensure_mutation_allowed(
            robot.settings,
            risk_level=MODULE_RECONNECT_DESCRIPTOR.risk_level,
            capability_name=MODULE_RECONNECT_DESCRIPTOR.name,
        )
        inventory = await client.list_modules()
        temps = inventory.temperature_modules()
        if serial:
            temps = [m for m in temps if m.serial_number == serial]
        if len(temps) != 1:
            return PhaseResult(
                phase=phase,
                passed=False,
                detail=f"expected exactly one temperature module, got {len(temps)}",
                inventory=_inventory_summary(inventory),
                elapsed_seconds=time.monotonic() - started,
            )
        mod = temps[0]
        set_cmd = await client.set_temperature_and_wait(
            module_id=mod.id,
            celsius=smoke_celsius,
        )
        # Brief settle so live data can refresh, then deactivate.
        await client.list_modules()
        off_cmd = await client.deactivate_temperature(module_id=mod.id)
        after = await client.list_modules()
        still = after.by_serial(mod.serial_number)
        ok = (
            len(still) == 1
            and not after.duplicate_serials()
            and isinstance(set_cmd.get("data"), dict)
            and set_cmd["data"].get("status") == "succeeded"
            and isinstance(off_cmd.get("data"), dict)
            and off_cmd["data"].get("status") == "succeeded"
        )
        detail = (
            f"set {smoke_celsius}C -> {set_cmd.get('data', {}).get('status')}; "
            f"deactivate -> {off_cmd.get('data', {}).get('status')}; "
            f"live_temp={still[0].current_temperature if still else None}"
        )
        result = PhaseResult(
            phase=phase,
            passed=ok,
            detail=detail,
            inventory=_inventory_summary(after),
            elapsed_seconds=time.monotonic() - started,
            command={"set": set_cmd, "deactivate": off_cmd},
        )
        robot.raw_evidence["module_reconnect_smoke"] = result.model_dump(mode="json")
        return result

    raise ValueError(f"Unknown phase: {phase}")
