"""Protocol-run client (create / list / inspect / actions).

Source: ``robot-server/robot_server/runs/router/``.

``play`` / ``stop`` are physical-motion adjacent; only call from gated
seed-run capabilities when the operator has explicitly requested live play.
"""

from __future__ import annotations

from typing import Any, Literal

from flex_testing_agent.clients.session import RobotHttpSession

RunActionType = Literal[
    "play",
    "pause",
    "stop",
    "resume-from-recovery",
    "resume-from-recovery-assuming-false-positive",
]


def _data_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("data")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _data_object(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("data")
    return raw if isinstance(raw, dict) else payload


class RunsClient:
    """Atomic client for ``/runs`` resources."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def list_runs(self) -> dict[str, Any]:
        """GET ``/runs`` envelope."""
        return await self._session.get_json("/runs")

    async def list_run_summaries(self) -> list[dict[str, Any]]:
        """Return run objects from ``GET /runs``."""
        return _data_list(await self.list_runs())

    async def get_run(self, run_id: str) -> dict[str, Any]:
        """GET ``/runs/{runId}``."""
        return await self._session.get_json(f"/runs/{run_id}")

    async def create_run(
        self,
        *,
        protocol_id: str | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """POST ``/runs`` (creates a run; does not play)."""
        body: dict[str, Any] = {"data": {}}
        if protocol_id is not None:
            body["data"]["protocolId"] = protocol_id
        return await self._session.post_json(
            "/runs",
            json_body=body,
            timeout=timeout,
            expected_status=(201,),
        )

    async def set_current(self, run_id: str, *, current: bool) -> dict[str, Any]:
        """PATCH ``/runs/{runId}`` current flag (uncurrent / make current)."""
        return await self._session.patch_json(
            f"/runs/{run_id}",
            json_body={"data": {"current": current}},
            expected_status=(200,),
        )

    async def sign_off(self, run_id: str, *, signed_by: str) -> dict[str, Any]:
        """PATCH ``/runs/{runId}`` with CRS protocol-log signoff."""
        return await self._session.patch_json(
            f"/runs/{run_id}",
            json_body={"data": {"signedBy": signed_by}},
            expected_status=(200,),
        )

    async def create_action(
        self,
        run_id: str,
        action_type: RunActionType,
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """POST ``/runs/{runId}/actions`` (play / pause / stop / …)."""
        return await self._session.post_json(
            f"/runs/{run_id}/actions",
            json_body={"data": {"actionType": action_type}},
            timeout=timeout,
            expected_status=(201,),
        )

    async def play(self, run_id: str, *, timeout: float = 60.0) -> dict[str, Any]:
        """Start or resume a run (physical motion may begin)."""
        return await self.create_action(run_id, "play", timeout=timeout)

    async def stop(self, run_id: str, *, timeout: float = 60.0) -> dict[str, Any]:
        """Stop (cancel) a run."""
        return await self.create_action(run_id, "stop", timeout=timeout)

    async def pause(self, run_id: str, *, timeout: float = 60.0) -> dict[str, Any]:
        """Pause a running run."""
        return await self.create_action(run_id, "pause", timeout=timeout)

    def status_from_run(self, payload: dict[str, Any]) -> str | None:
        """Extract run status string from a get/create envelope."""
        data = _data_object(payload)
        status = data.get("status")
        return str(status) if status is not None else None

    async def delete_run(self, run_id: str) -> dict[str, Any]:
        """DELETE ``/runs/{runId}``."""
        return await self._session.delete_json(
            f"/runs/{run_id}",
            expected_status=(200, 204),
        )

    async def list_commands(self, run_id: str) -> dict[str, Any]:
        """GET ``/runs/{runId}/commands``."""
        return await self._session.get_json(f"/runs/{run_id}/commands")

    async def get_command(self, run_id: str, command_id: str) -> dict[str, Any]:
        """GET ``/runs/{runId}/commands/{commandId}``."""
        return await self._session.get_json(f"/runs/{run_id}/commands/{command_id}")

    async def get_current_state(self, run_id: str) -> dict[str, Any]:
        """GET ``/runs/{runId}/currentState``."""
        return await self._session.get_json(f"/runs/{run_id}/currentState")

    async def get_command_errors(self, run_id: str) -> dict[str, Any]:
        """GET ``/runs/{runId}/commandErrors``."""
        return await self._session.get_json(f"/runs/{run_id}/commandErrors")

    async def get_command_annotations(self, run_id: str) -> dict[str, Any]:
        """GET ``/runs/{runId}/commandAnnotations``."""
        return await self._session.get_json(f"/runs/{run_id}/commandAnnotations")

    async def get_commands_as_pre_serialized_list(self, run_id: str) -> dict[str, Any]:
        """GET ``/runs/{runId}/commandsAsPreSerializedList``."""
        return await self._session.get_json(
            f"/runs/{run_id}/commandsAsPreSerializedList"
        )

    async def get_error_recovery_policy(self, run_id: str) -> dict[str, Any]:
        """GET ``/runs/{runId}/errorRecoveryPolicy``."""
        return await self._session.get_json(f"/runs/{run_id}/errorRecoveryPolicy")

    async def get_loaded_labware_definitions(self, run_id: str) -> dict[str, Any]:
        """GET ``/runs/{runId}/loaded_labware_definitions``."""
        return await self._session.get_json(
            f"/runs/{run_id}/loaded_labware_definitions"
        )

    async def get_run_camera_settings(
        self, run_id: str, camera_id: str = "ot_system_camera"
    ) -> dict[str, Any]:
        """GET ``/runs/{runId}/cameraSettings/{cameraId}``."""
        return await self._session.get_json(
            f"/runs/{run_id}/cameraSettings/{camera_id}"
        )

    def run_id_from_create(self, payload: dict[str, Any]) -> str | None:
        """Extract run id from a create / get envelope."""
        data = _data_object(payload)
        run_id = data.get("id")
        return str(run_id) if run_id is not None else None
