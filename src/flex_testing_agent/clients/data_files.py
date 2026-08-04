"""Data-files client (CSV upload / list / download).

Source: ``robot-server/robot_server/data_files/router.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession


def _data_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("data")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _data_object(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("data")
    return raw if isinstance(raw, dict) else payload


class DataFilesClient:
    """Atomic client for ``/dataFiles`` resources."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def list_data_files(self) -> dict[str, Any]:
        """GET ``/dataFiles`` envelope."""
        return await self._session.get_json("/dataFiles")

    async def list_data_file_summaries(self) -> list[dict[str, Any]]:
        """Return data-file objects from ``GET /dataFiles``."""
        return _data_list(await self.list_data_files())

    async def get_data_file(self, data_file_id: str) -> dict[str, Any]:
        """GET ``/dataFiles/{dataFileId}``."""
        return await self._session.get_json(f"/dataFiles/{data_file_id}")

    async def download_data_file(self, data_file_id: str) -> bytes:
        """GET ``/dataFiles/{dataFileId}/download`` bytes."""
        content, _ = await self._session.get_bytes(
            f"/dataFiles/{data_file_id}/download"
        )
        return content

    async def upload_csv(
        self,
        file_path: Path,
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """POST multipart ``/dataFiles`` with a CSV file."""
        content = file_path.read_bytes()
        return await self._session.post_multipart(
            "/dataFiles",
            files=[("file", (file_path.name, content, "text/csv"))],
            timeout=timeout,
            expected_status=(200, 201),
        )

    async def delete_data_file(self, data_file_id: str) -> dict[str, Any]:
        """DELETE ``/dataFiles/{dataFileId}``."""
        return await self._session.delete_json(
            f"/dataFiles/{data_file_id}",
            expected_status=(200, 204),
        )

    async def list_run_files(self, run_id: str) -> dict[str, Any]:
        """GET ``/dataFiles/{runId}/all``."""
        return await self._session.get_json(f"/dataFiles/{run_id}/all")

    async def list_run_images(self, run_id: str) -> dict[str, Any]:
        """GET ``/dataFiles/{runId}/images``."""
        return await self._session.get_json(f"/dataFiles/{run_id}/images")

    def data_file_id_from_upload(self, payload: dict[str, Any]) -> str | None:
        """Extract data-file id from an upload / get envelope."""
        data = _data_object(payload)
        file_id = data.get("id")
        return str(file_id) if file_id is not None else None
