"""Probe all catalogued read-only endpoints and optionally capture a photo."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.camera import CameraClient
from flex_testing_agent.clients.readonly import ReadonlyClient, ReadonlyProbeReport
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

PROBE_DESCRIPTOR = CapabilityDescriptor(
    name="probe_readonly",
    description=(
        "Exercise catalogued read-only Flex HTTP endpoints and summarize state."
    ),
    risk_level=RiskLevel.READ_ONLY,
    mutates_robot=False,
    evidence_produced=["readonly_probe.json", "robot_state_summary.json"],
)

PICTURE_DESCRIPTOR = CapabilityDescriptor(
    name="take_picture",
    description="Capture a JPEG from the Flex camera (enables camera if needed).",
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    mutates_robot=True,
    requires_cleanup=False,
    evidence_produced=["camera.jpg"],
)


class RobotStateSummary(BaseModel):
    """Concise robot state derived from a readonly probe."""

    name: str | None = None
    host: str | None = None
    robot_model: str | None = None
    serial: str | None = None
    system_version: str | None = None
    api_version: str | None = None
    update_server_version: str | None = None
    access_control: Any = None
    estop: Any = None
    door: Any = None
    lights: Any = None
    motors_engaged: Any = None
    subsystems: Any = None
    instruments: Any = None
    modules: Any = None
    runs_count: int | None = None
    protocols_count: int | None = None
    current_maintenance_run: Any = None
    networking: Any = None
    camera: Any = None
    camera_stream: Any = None
    system_time: Any = None
    probe_ok: int = 0
    probe_failed: int = 0
    failed_endpoints: list[str] = Field(default_factory=list)


class ProbeResult(BaseModel):
    """Probe + optional picture outcome."""

    summary: RobotStateSummary
    probe: dict[str, Any]
    picture_path: str | None = None
    picture_error: str | None = None


def summarize_probe(
    report: ReadonlyProbeReport,
    *,
    host: str | None = None,
) -> RobotStateSummary:
    """Build a human-oriented summary from probe payloads."""
    health = report.payload("health") or {}
    update_health = report.payload("update_health") or {}
    runs = report.payload("runs") or {}
    protocols = report.payload("protocols") or {}
    failed = [f"{r.path} ({r.status_code})" for r in report.results if not r.ok]

    def _count_data(payload: Any) -> int | None:
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return len(payload["data"])
        return None

    subsystems = report.payload("subsystems_status")
    instruments = report.payload("instruments")
    modules = report.payload("modules")

    return RobotStateSummary(
        name=health.get("name") if isinstance(health, dict) else None,
        host=host,
        robot_model=health.get("robot_model") if isinstance(health, dict) else None,
        serial=health.get("robot_serial") if isinstance(health, dict) else None,
        system_version=(
            health.get("system_version") if isinstance(health, dict) else None
        ),
        api_version=health.get("api_version") if isinstance(health, dict) else None,
        update_server_version=(
            update_health.get("updateServerVersion")
            if isinstance(update_health, dict)
            else None
        ),
        access_control=report.payload("access_control_enabled"),
        estop=report.payload("estop_status"),
        door=report.payload("door_status"),
        lights=report.payload("lights"),
        motors_engaged=report.payload("motors_engaged"),
        subsystems=subsystems,
        instruments=instruments,
        modules=modules,
        runs_count=_count_data(runs),
        protocols_count=_count_data(protocols),
        current_maintenance_run=report.payload("maintenance_current_run"),
        networking=report.payload("networking_status"),
        camera=report.payload("camera"),
        camera_stream=report.payload("camera_stream"),
        system_time=report.payload("system_time"),
        probe_ok=report.ok_count,
        probe_failed=report.fail_count,
        failed_endpoints=failed,
    )


async def probe_robot(
    robot: FlexRobot,
    *,
    take_picture: bool = True,
    picture_path: Path | None = None,
    enable_camera_if_needed: bool = True,
) -> ProbeResult:
    """Probe read-only endpoints and optionally capture a camera image."""
    readonly = ReadonlyClient(robot.session)
    report = await readonly.probe_all()
    robot.raw_evidence["readonly_probe"] = {
        "ok": report.ok_count,
        "failed": report.fail_count,
        "results": [
            {
                "name": r.name,
                "path": r.path,
                "group": r.group,
                "ok": r.ok,
                "status_code": r.status_code,
                "error": r.error,
            }
            for r in report.results
        ],
    }
    for key in (
        "health",
        "update_health",
        "access_control_enabled",
        "estop_status",
        "door_status",
        "subsystems_status",
        "instruments",
        "modules",
        "camera",
        "networking_status",
    ):
        payload = report.payload(key)
        if payload is not None:
            robot.raw_evidence[key] = payload

    summary = summarize_probe(report, host=robot.settings.robot_host)
    robot.raw_evidence["robot_state_summary"] = summary.model_dump(mode="json")

    picture_dest = picture_path
    picture_error: str | None = None
    if take_picture:
        if picture_dest is None:
            picture_dest = (
                robot.settings.ensure_artifact_directory() / "camera" / "kansasflex.jpg"
            )
        try:
            ensure_mutation_allowed(
                robot.settings,
                risk_level=PICTURE_DESCRIPTOR.risk_level,
                capability_name=PICTURE_DESCRIPTOR.name,
            )
            camera = CameraClient(robot.session)
            status = await camera.get_camera()
            enabled = bool(status.get("cameraEnabled"))
            if enable_camera_if_needed and not enabled:
                log.info("enabling_camera")
                status = await camera.set_camera_enabled(camera_enabled=True)
                robot.raw_evidence["camera_enable"] = status
            await camera.save_picture(picture_dest)
            robot.raw_evidence["picture_path"] = str(picture_dest)
        except Exception as exc:
            picture_error = str(exc)
            picture_dest = None
            log.info("picture_failed", error=picture_error)

    return ProbeResult(
        summary=summary,
        probe=robot.raw_evidence["readonly_probe"],
        picture_path=str(picture_dest) if picture_dest else None,
        picture_error=picture_error,
    )
