"""Scripted labware-position-check seed via maintenance_runs + /labwareOffsets.

Not a Protocol API ``.py`` file. Drives Flex LPC-shaped interactions over HTTP:

1. ``POST /maintenance_runs``
2. ``loadPipette`` / ``loadLabware`` / ``home`` / ``moveToWell`` / ``moveRelative`` jogs
3. ``savePosition`` (command history)
4. ``POST /labwareOffsets`` to persist a known small vector for that labware

Requires a clear deck slot for the virtual tiprack (default **C2**). Trash A3 and
HS D1 may remain. Door should be closed. PHYSICAL_MOTION.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.maintenance_runs import MaintenanceRunsClient
from flex_testing_agent.logging import get_logger
from flex_testing_agent.orchestration.timing import TimingSession
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

# Flex PE load names (OpenAPI PipetteNameType / shared-data tiprack).
DEFAULT_PIPETTE_NAME = "p50_single_flex"
DEFAULT_PIPETTE_MOUNT = "right"
DEFAULT_PIPETTE_ID = "seed-lpc-pipette"
DEFAULT_LABWARE_ID = "seed-lpc-tiprack"
DEFAULT_LABWARE_LOAD_NAME = "opentrons_flex_96_tiprack_50ul"
DEFAULT_LABWARE_NAMESPACE = "opentrons"
DEFAULT_LABWARE_VERSION = 1
DEFAULT_SLOT = "C2"
DEFAULT_DEFINITION_URI = (
    f"{DEFAULT_LABWARE_NAMESPACE}/{DEFAULT_LABWARE_LOAD_NAME}/{DEFAULT_LABWARE_VERSION}"
)
# Stay high above the virtual tiprack (no physical labware required).
DEFAULT_APPROACH_Z_MM = 40.0
# Small scripted jogs (LPC-like), then undo X so we leave near approach.
DEFAULT_JOGS: tuple[tuple[str, float], ...] = (
    ("x", 1.0),
    ("y", -1.0),
    ("z", 0.5),
    ("x", -1.0),
)
# Persisted offset vector (mm). Distinct so GET /labwareOffsets shows seed data.
DEFAULT_OFFSET_VECTOR = {"x": 0.11, "y": -0.07, "z": 0.03}


class SeedLpcResult(BaseModel):
    """Outcome of the scripted LPC seed."""

    ok: bool
    maintenance_run_id: str | None = None
    offset_id: str | None = None
    definition_uri: str = DEFAULT_DEFINITION_URI
    slot: str = DEFAULT_SLOT
    commands: list[str] = Field(default_factory=list)
    detail: str | None = None
    timings: dict[str, float] = Field(default_factory=dict)


async def _run_command(
    client: MaintenanceRunsClient,
    run_id: str,
    command: dict[str, Any],
    *,
    timeout_ms: int = 120_000,
) -> dict[str, Any]:
    payload = await client.enqueue_command(
        run_id,
        command,
        wait_until_complete=True,
        timeout_ms=timeout_ms,
    )
    status = client.command_status(payload)
    if status != "succeeded":
        detail = client.command_error_detail(payload) or f"status={status}"
        raise RobotApiError(
            f"maintenance command {command.get('commandType')} failed: {detail}",
            path=f"/maintenance_runs/{run_id}/commands",
            body=str(payload)[:2000],
        )
    return payload


async def run_seed_lpc_scripted(
    robot: FlexRobot,
    timing: TimingSession,
    *,
    slot: str = DEFAULT_SLOT,
    pipette_name: str = DEFAULT_PIPETTE_NAME,
    pipette_mount: str = DEFAULT_PIPETTE_MOUNT,
    offset_vector: dict[str, float] | None = None,
) -> SeedLpcResult:
    """Execute scripted LPC jogs and persist a labware offset."""
    vector = offset_vector or dict(DEFAULT_OFFSET_VECTOR)
    maintenance = robot.maintenance_runs
    offsets = robot.labware_offsets
    commands_done: list[str] = []
    local_timings: dict[str, float] = {}
    prefix = "seed.lpc_scripted"

    # Drop any leftover maintenance run so create can succeed.
    try:
        current = await maintenance.get_current()
        data = current.get("data")
        if isinstance(data, dict) and data.get("id"):
            await maintenance.delete(str(data["id"]))
    except RobotApiError:
        pass

    timing.start(f"{prefix}.create_maintenance_run")
    created = await maintenance.create()
    timing.stop(f"{prefix}.create_maintenance_run")
    span = timing.spans[-1]
    if span.duration_seconds is not None:
        local_timings["lpc.create_maintenance_run"] = span.duration_seconds
    run_id = maintenance.run_id_from_create(created)
    if run_id is None:
        return SeedLpcResult(ok=False, detail="maintenance run create missing id")

    try:
        async with timing.aspan(f"{prefix}.commands"):
            await _run_command(
                maintenance,
                run_id,
                {
                    "commandType": "loadPipette",
                    "params": {
                        "pipetteName": pipette_name,
                        "mount": pipette_mount,
                        "pipetteId": DEFAULT_PIPETTE_ID,
                    },
                },
            )
            commands_done.append("loadPipette")

            await _run_command(
                maintenance,
                run_id,
                {
                    "commandType": "loadLabware",
                    "params": {
                        "location": {"slotName": slot},
                        "loadName": DEFAULT_LABWARE_LOAD_NAME,
                        "namespace": DEFAULT_LABWARE_NAMESPACE,
                        "version": DEFAULT_LABWARE_VERSION,
                        "labwareId": DEFAULT_LABWARE_ID,
                    },
                },
            )
            commands_done.append("loadLabware")

            await _run_command(
                maintenance,
                run_id,
                {"commandType": "home", "params": {}},
                timeout_ms=180_000,
            )
            commands_done.append("home")

            await _run_command(
                maintenance,
                run_id,
                {
                    "commandType": "moveToWell",
                    "params": {
                        "pipetteId": DEFAULT_PIPETTE_ID,
                        "labwareId": DEFAULT_LABWARE_ID,
                        "wellName": "A1",
                        "wellLocation": {
                            "origin": "top",
                            "offset": {"x": 0, "y": 0, "z": DEFAULT_APPROACH_Z_MM},
                        },
                    },
                },
                timeout_ms=180_000,
            )
            commands_done.append("moveToWell")

            for axis, distance in DEFAULT_JOGS:
                await _run_command(
                    maintenance,
                    run_id,
                    {
                        "commandType": "moveRelative",
                        "params": {
                            "pipetteId": DEFAULT_PIPETTE_ID,
                            "axis": axis,
                            "distance": distance,
                        },
                    },
                )
                commands_done.append(f"moveRelative:{axis}:{distance}")

            await _run_command(
                maintenance,
                run_id,
                {
                    "commandType": "savePosition",
                    "params": {
                        "pipetteId": DEFAULT_PIPETTE_ID,
                        "positionId": "seed-lpc-confirm",
                        "failOnNotHomed": False,
                    },
                },
            )
            commands_done.append("savePosition")

            await _run_command(
                maintenance,
                run_id,
                {"commandType": "home", "params": {}},
                timeout_ms=180_000,
            )
            commands_done.append("home")

        timing.start(f"{prefix}.store_offset")
        stored = await offsets.create_offset(
            {
                "definitionUri": DEFAULT_DEFINITION_URI,
                "locationSequence": [
                    {"kind": "onAddressableArea", "addressableAreaName": slot},
                ],
                "vector": vector,
            }
        )
        timing.stop(f"{prefix}.store_offset")
        span = timing.spans[-1]
        if span.duration_seconds is not None:
            local_timings["lpc.store_offset"] = span.duration_seconds
        offset_id = offsets.offset_id_from_create(stored)
        robot.raw_evidence["seed_lpc_offset"] = stored
        robot.raw_evidence["seed_lpc_maintenance_run"] = await maintenance.get(run_id)

        return SeedLpcResult(
            ok=True,
            maintenance_run_id=run_id,
            offset_id=offset_id,
            definition_uri=DEFAULT_DEFINITION_URI,
            slot=slot,
            commands=commands_done,
            detail=f"stored offset vector={vector}",
            timings=local_timings,
        )
    except Exception as exc:
        log.info("seed_lpc_failed", run_id=run_id, error=str(exc))
        return SeedLpcResult(
            ok=False,
            maintenance_run_id=run_id,
            definition_uri=DEFAULT_DEFINITION_URI,
            slot=slot,
            commands=commands_done,
            detail=str(exc),
            timings=local_timings,
        )
    finally:
        try:
            await maintenance.delete(run_id)
        except RobotApiError as exc:
            log.info("seed_lpc_delete_failed", run_id=run_id, error=str(exc))
