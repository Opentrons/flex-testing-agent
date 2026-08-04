"""Maintenance-run client (scripted LPC / jog flow).

Source: ``robot-server`` ``/maintenance_runs`` routes. Commands execute
immediately when enqueued (unlike protocol runs). Prefer
``waitUntilComplete=true`` for sequential jog scripts.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from flex_testing_agent.clients.session import RobotHttpSession


def _data_object(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("data")
    return raw if isinstance(raw, dict) else payload


class MaintenanceRunsClient:
    """Atomic client for ``/maintenance_runs`` resources."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        labware_offsets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """POST ``/maintenance_runs``."""
        data: dict[str, Any] = {}
        if labware_offsets is not None:
            data["labwareOffsets"] = labware_offsets
        return await self._session.post_json(
            "/maintenance_runs",
            json_body={"data": data},
            expected_status=(200, 201),
        )

    async def get(self, run_id: str) -> dict[str, Any]:
        """GET ``/maintenance_runs/{runId}``."""
        return await self._session.get_json(f"/maintenance_runs/{run_id}")

    async def get_current(self) -> dict[str, Any]:
        """GET ``/maintenance_runs/current_run`` (404 when none)."""
        return await self._session.get_json(
            "/maintenance_runs/current_run",
            expected_status=(200, 404),
        )

    async def delete(self, run_id: str) -> dict[str, Any]:
        """DELETE ``/maintenance_runs/{runId}``."""
        return await self._session.delete_json(
            f"/maintenance_runs/{run_id}",
            expected_status=(200, 204),
        )

    async def enqueue_command(
        self,
        run_id: str,
        command: dict[str, Any],
        *,
        wait_until_complete: bool = True,
        timeout_ms: int = 120_000,
        requires_closed_door: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """POST ``/maintenance_runs/{runId}/commands``."""
        query = urlencode(
            {
                "waitUntilComplete": "true" if wait_until_complete else "false",
                "timeout": str(timeout_ms),
                "requiresClosedDoor": "true" if requires_closed_door else "false",
            }
        )
        # Request timeout should cover waitUntilComplete timeout.
        http_timeout = timeout
        if http_timeout is None:
            http_timeout = max(30.0, (timeout_ms / 1000.0) + 15.0)
        return await self._session.post_json(
            f"/maintenance_runs/{run_id}/commands?{query}",
            json_body={"data": command},
            timeout=http_timeout,
            expected_status=(200, 201),
        )

    async def list_commands(self, run_id: str) -> dict[str, Any]:
        """GET ``/maintenance_runs/{runId}/commands``."""
        return await self._session.get_json(f"/maintenance_runs/{run_id}/commands")

    async def add_labware_offsets(
        self, run_id: str, offsets: dict[str, Any] | list[dict[str, Any]]
    ) -> dict[str, Any]:
        """POST ``/maintenance_runs/{runId}/labware_offsets``."""
        return await self._session.post_json(
            f"/maintenance_runs/{run_id}/labware_offsets",
            json_body={"data": offsets},
            expected_status=(200, 201),
        )

    def run_id_from_create(self, payload: dict[str, Any]) -> str | None:
        """Extract maintenance run id from create response."""
        data = _data_object(payload)
        run_id = data.get("id")
        return str(run_id) if run_id else None

    def command_id_from_enqueue(self, payload: dict[str, Any]) -> str | None:
        """Extract command id from an enqueue / get-command envelope."""
        data = _data_object(payload)
        command_id = data.get("id")
        return str(command_id) if command_id is not None else None

    def command_status(self, payload: dict[str, Any]) -> str | None:
        """Extract command status from enqueue response."""
        data = _data_object(payload)
        status = data.get("status")
        return str(status) if status is not None else None

    def command_error_detail(self, payload: dict[str, Any]) -> str | None:
        """Extract error detail from a failed command envelope."""
        data = _data_object(payload)
        err = data.get("error")
        if isinstance(err, dict):
            detail = err.get("detail") or err.get("errorType")
            return str(detail) if detail else str(err)
        return None
