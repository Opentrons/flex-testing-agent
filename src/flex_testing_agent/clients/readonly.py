"""Read-only Flex API endpoint catalog and probe helper.

Paths are derived from Opentrons ``robot-server``, ``update-server``, and
``auth-server`` routers. This client only issues GET requests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.session import RobotHttpSession


@dataclass(frozen=True)
class ReadonlyEndpoint:
    """One read-only HTTP endpoint to exercise."""

    name: str
    path: str
    group: str
    timeout_seconds: float = 30.0
    notes: str = ""
    # Status codes that count as a successful probe (e.g. no current resource).
    acceptable_status: tuple[int, ...] = (200,)


# Core Flex read-only surface used for state summaries.
READONLY_ENDPOINTS: tuple[ReadonlyEndpoint, ...] = (
    ReadonlyEndpoint("health", "/health", "system"),
    ReadonlyEndpoint("update_health", "/server/update/health", "system"),
    ReadonlyEndpoint("server_name", "/server/name", "system"),
    ReadonlyEndpoint(
        "ssh_keys",
        "/server/ssh_keys",
        "system",
        notes="Often 403 without elevated credentials.",
        acceptable_status=(200, 403),
    ),
    ReadonlyEndpoint("system_time", "/system/time", "system"),
    ReadonlyEndpoint(
        "access_control_enabled",
        "/auth/settings/accessControlEnabled",
        "auth",
    ),
    ReadonlyEndpoint("auth_settings", "/auth/settings", "auth"),
    ReadonlyEndpoint("estop_status", "/robot/control/estopStatus", "robot"),
    ReadonlyEndpoint("door_status", "/robot/door/status", "robot"),
    ReadonlyEndpoint("lights", "/robot/lights", "robot"),
    ReadonlyEndpoint("motors_engaged", "/motors/engaged", "robot"),
    ReadonlyEndpoint("subsystems_status", "/subsystems/status", "robot"),
    ReadonlyEndpoint(
        "subsystems_updates_current",
        "/subsystems/updates/current",
        "robot",
    ),
    ReadonlyEndpoint(
        "subsystems_updates_all",
        "/subsystems/updates/all",
        "robot",
    ),
    ReadonlyEndpoint("instruments", "/instruments", "hardware"),
    ReadonlyEndpoint("modules", "/modules", "hardware"),
    ReadonlyEndpoint("pipettes", "/pipettes", "hardware"),
    ReadonlyEndpoint("runs", "/runs", "protocols"),
    ReadonlyEndpoint("protocols", "/protocols", "protocols"),
    ReadonlyEndpoint("protocol_ids", "/protocols/ids", "protocols"),
    ReadonlyEndpoint(
        "maintenance_current_run",
        "/maintenance_runs/current_run",
        "protocols",
        notes="404 when no maintenance run is active.",
        acceptable_status=(200, 404),
    ),
    ReadonlyEndpoint("commands", "/commands", "protocols"),
    ReadonlyEndpoint("sessions", "/sessions", "protocols"),
    ReadonlyEndpoint("data_files", "/dataFiles", "protocols"),
    ReadonlyEndpoint("settings", "/settings", "settings"),
    ReadonlyEndpoint("settings_robot", "/settings/robot", "settings"),
    ReadonlyEndpoint(
        "settings_reset_options",
        "/settings/reset/options",
        "settings",
    ),
    ReadonlyEndpoint(
        "access_control_settings",
        "/accessControl/settings",
        "settings",
    ),
    ReadonlyEndpoint(
        "error_recovery_settings",
        "/errorRecovery/settings",
        "settings",
    ),
    ReadonlyEndpoint("calibration_status", "/calibration/status", "calibration"),
    ReadonlyEndpoint(
        "pipette_offset",
        "/calibration/pipette_offset",
        "calibration",
        notes="Legacy OT-2 path; Flex often returns 403.",
        acceptable_status=(200, 403),
    ),
    ReadonlyEndpoint(
        "tip_length",
        "/calibration/tip_length",
        "calibration",
        notes="Legacy OT-2 path; Flex often returns 403.",
        acceptable_status=(200, 403),
    ),
    ReadonlyEndpoint(
        "labware_calibrations",
        "/labware/calibrations",
        "calibration",
    ),
    ReadonlyEndpoint("labware_offsets", "/labwareOffsets", "calibration"),
    ReadonlyEndpoint("deck_configuration", "/deck_configuration", "calibration"),
    ReadonlyEndpoint("networking_status", "/networking/status", "network"),
    ReadonlyEndpoint("wifi_keys", "/wifi/keys", "network"),
    ReadonlyEndpoint("wifi_eap_options", "/wifi/eap-options", "network"),
    ReadonlyEndpoint(
        "wifi_list",
        "/wifi/list",
        "network",
        timeout_seconds=60.0,
        notes="Wi-Fi scan; may be slow.",
    ),
    ReadonlyEndpoint("camera", "/camera", "camera"),
    ReadonlyEndpoint("camera_stream", "/camera/stream", "camera"),
    ReadonlyEndpoint(
        "camera_stream_settings",
        "/camera/stream/settings",
        "camera",
    ),
    ReadonlyEndpoint(
        "camera_capture_settings",
        "/camera/cameraSettings/ot_system_camera",
        "camera",
    ),
)


@dataclass
class EndpointProbeResult:
    """Result of probing one read-only endpoint."""

    name: str
    path: str
    group: str
    ok: bool
    status_code: int | None = None
    error: str | None = None
    payload: Any = None


@dataclass
class ReadonlyProbeReport:
    """Aggregate probe results."""

    results: list[EndpointProbeResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    def by_name(self, name: str) -> EndpointProbeResult | None:
        for result in self.results:
            if result.name == name:
                return result
        return None

    def payload(self, name: str) -> Any:
        result = self.by_name(name)
        return None if result is None else result.payload


class ReadonlyClient:
    """Exercise the Flex read-only HTTP surface."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def get(self, path: str, *, timeout: float | None = None) -> Any:
        """GET JSON (object or other JSON value) from an arbitrary path."""
        response = await self._session._request_raw("GET", path, timeout=timeout)
        if not response.content:
            return None
        return response.json()

    async def probe_all(
        self,
        endpoints: tuple[ReadonlyEndpoint, ...] = READONLY_ENDPOINTS,
    ) -> ReadonlyProbeReport:
        """GET every catalogued read-only endpoint and collect results."""
        report = ReadonlyProbeReport()
        for endpoint in endpoints:
            try:
                payload = await self.get(
                    endpoint.path, timeout=endpoint.timeout_seconds
                )
                report.results.append(
                    EndpointProbeResult(
                        name=endpoint.name,
                        path=endpoint.path,
                        group=endpoint.group,
                        ok=True,
                        status_code=200,
                        payload=payload,
                    )
                )
            except RobotApiError as exc:
                acceptable = (
                    exc.status_code is not None
                    and exc.status_code in endpoint.acceptable_status
                )
                report.results.append(
                    EndpointProbeResult(
                        name=endpoint.name,
                        path=endpoint.path,
                        group=endpoint.group,
                        ok=acceptable,
                        status_code=exc.status_code,
                        error=None if acceptable else str(exc),
                        payload=None,
                    )
                )
        return report
