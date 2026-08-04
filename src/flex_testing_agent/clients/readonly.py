"""Read-only Flex API endpoint catalog and probe helper.

GET coverage is driven by ``catalog.endpoints_for_crs_off_get_probe`` (full Flex
HTTP inventory for CRS-off Tier A). This client only issues GET requests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from flex_testing_agent.catalog import EndpointSpec, endpoints_for_crs_off_get_probe
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.session import RobotHttpSession

# Stable probe names used by summarize_probe / evidence keys (path → name).
_PROBE_NAME_BY_PATH: dict[str, str] = {
    "/health": "health",
    "/server/update/health": "update_health",
    "/server/name": "server_name",
    "/server/ssh_keys": "ssh_keys",
    "/system/time": "system_time",
    "/auth/settings/accessControlEnabled": "access_control_enabled",
    "/auth/settings": "auth_settings",
    "/robot/control/estopStatus": "estop_status",
    "/robot/door/status": "door_status",
    "/robot/lights": "lights",
    "/motors/engaged": "motors_engaged",
    "/subsystems/status": "subsystems_status",
    "/subsystems/updates/current": "subsystems_updates_current",
    "/subsystems/updates/all": "subsystems_updates_all",
    "/instruments": "instruments",
    "/modules": "modules",
    "/pipettes": "pipettes",
    "/runs": "runs",
    "/protocols": "protocols",
    "/protocols/ids": "protocol_ids",
    "/maintenance_runs/current_run": "maintenance_current_run",
    "/commands": "commands",
    "/sessions": "sessions",
    "/dataFiles": "data_files",
    "/settings": "settings",
    "/settings/robot": "settings_robot",
    "/settings/reset/options": "settings_reset_options",
    "/accessControl/settings": "access_control_settings",
    "/errorRecovery/settings": "error_recovery_settings",
    "/calibration/status": "calibration_status",
    "/calibration/pipette_offset": "pipette_offset",
    "/calibration/tip_length": "tip_length",
    "/labware/calibrations": "labware_calibrations",
    "/labwareOffsets": "labware_offsets",
    "/deck_configuration": "deck_configuration",
    "/networking/status": "networking_status",
    "/wifi/keys": "wifi_keys",
    "/wifi/eap-options": "wifi_eap_options",
    "/wifi/list": "wifi_list",
    "/camera": "camera",
    "/camera/stream": "camera_stream",
    "/camera/stream/settings": "camera_stream_settings",
    "/camera/cameraSettings/ot_system_camera": "camera_capture_settings",
}


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


def _probe_name(path: str, catalog_name: str) -> str:
    if path in _PROBE_NAME_BY_PATH:
        return _PROBE_NAME_BY_PATH[path]
    if catalog_name.startswith("get_"):
        return catalog_name.removeprefix("get_")
    return catalog_name


def _from_spec(spec: EndpointSpec) -> ReadonlyEndpoint:
    return ReadonlyEndpoint(
        name=_probe_name(spec.path, spec.name),
        path=spec.path,
        group=spec.group,
        timeout_seconds=spec.timeout_seconds,
        notes=spec.notes,
        acceptable_status=spec.crs_off_acceptable_status,
    )


# Concrete parameterized GETs that CRS-off Tier A still exercises with known IDs.
_EXTRA_READONLY_ENDPOINTS: tuple[ReadonlyEndpoint, ...] = (
    ReadonlyEndpoint(
        name="camera_capture_settings",
        path="/camera/cameraSettings/ot_system_camera",
        group="camera",
    ),
)


# Core Flex read-only surface used for CRS-off state summaries / probe.
READONLY_ENDPOINTS: tuple[ReadonlyEndpoint, ...] = (
    tuple(_from_spec(spec) for spec in endpoints_for_crs_off_get_probe())
    + _EXTRA_READONLY_ENDPOINTS
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
    duration_seconds: float | None = None


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
            t0 = time.perf_counter()
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
                        duration_seconds=time.perf_counter() - t0,
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
                        duration_seconds=time.perf_counter() - t0,
                    )
                )
        return report
