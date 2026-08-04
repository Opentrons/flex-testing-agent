"""Put KansasFLEX into a documented known software / deck state.

Seed-run history (motion) is intentionally separate; see
``docs/known-state-and-latency.md``. This module covers clear data + deck
config so agents can re-establish a baseline one-off or from suites.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.capabilities.reset_data import reset_robot_data
from flex_testing_agent.clients.deck_configuration import (
    DeckConfigurationClient,
    kansas_deck_cutouts,
)
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.orchestration.timing import TimingSession
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

KNOWN_STATE_DESCRIPTOR = CapabilityDescriptor(
    name="known_state_setup",
    description=(
        "Baseline known state: optional robot-server data reset + Kansas deck "
        "configuration (HS D1, trash A3). Does not play protocols."
    ),
    risk_level=RiskLevel.DISRUPTIVE,
    mutates_robot=True,
    evidence_produced=["known_state.json", "timing"],
    preconditions=["ALLOW_MUTATIONS=true", "Deck physically matches Kansas baseline"],
)

DEFAULT_HS_SERIAL = "HSDVT22041138"


class KnownStateResult(BaseModel):
    """Outcome of known-state setup (non-motion phases)."""

    reset_options: dict[str, bool] | None = None
    deck_applied: bool = False
    heater_shaker_serial: str | None = None
    timing_path: str | None = None
    details: list[str] = Field(default_factory=list)


async def _resolve_hs_serial(robot: FlexRobot, fallback: str) -> str:
    try:
        inventory = await robot.modules.list_modules()
    except Exception:
        return fallback
    for mod in inventory.modules:
        if "heaterShaker" in mod.module_model and mod.serial_number:
            return mod.serial_number
    return fallback


async def setup_known_state(
    robot: FlexRobot,
    *,
    reset_data: bool = True,
    apply_deck: bool = True,
    heater_shaker_serial: str | None = None,
) -> KnownStateResult:
    """Reset robot-server data and/or apply Kansas deck configuration."""
    ensure_mutation_allowed(
        robot.settings,
        risk_level=KNOWN_STATE_DESCRIPTOR.risk_level,
        capability_name=KNOWN_STATE_DESCRIPTOR.name,
    )
    timing = TimingSession(
        label="known-state",
        robot_host=robot.settings.robot_host,
    )
    try:
        health = await robot.verify_health()
        timing.system_version = health.system_version
        timing.api_version = health.api_version
    except Exception as exc:
        timing.note(f"health unavailable: {exc}")

    details: list[str] = []
    reset_options: dict[str, bool] | None = None
    if reset_data:
        reset_result = await reset_robot_data(robot, timing=timing)
        reset_options = reset_result.options
        details.append(f"reset {sorted(reset_options)}")

    deck_applied = False
    serial = heater_shaker_serial
    if apply_deck:
        serial = serial or await _resolve_hs_serial(robot, DEFAULT_HS_SERIAL)
        cutouts = kansas_deck_cutouts(heater_shaker_serial=serial)
        client = DeckConfigurationClient(robot.session)
        async with timing.aspan("deck.put", meta={"hs_serial": serial}):
            payload = await client.put(cutouts)
        robot.raw_evidence["deck_configuration"] = payload
        deck_applied = True
        details.append(f"deck applied hs={serial}")

    path = timing.write(robot.settings.ensure_artifact_directory() / "timing")
    result = KnownStateResult(
        reset_options=reset_options,
        deck_applied=deck_applied,
        heater_shaker_serial=serial,
        timing_path=str(path),
        details=details,
    )
    robot.raw_evidence["known_state"] = result.model_dump(mode="json")
    log.info("known_state_setup_complete", **result.model_dump())
    return result


# Re-export for typing clarity in suites.
__all__ = [
    "KNOWN_STATE_DESCRIPTOR",
    "KnownStateResult",
    "setup_known_state",
]
