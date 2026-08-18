"""Protocol upload / list / analysis client.

Source: ``robot-server/robot_server/protocols/router.py``.
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


class ProtocolsClient:
    """Atomic client for ``/protocols`` resources."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def list_protocols(self) -> dict[str, Any]:
        """GET ``/protocols`` envelope."""
        return await self._session.get_json("/protocols")

    async def list_protocol_summaries(self) -> list[dict[str, Any]]:
        """Return protocol objects from ``GET /protocols``."""
        return _data_list(await self.list_protocols())

    async def list_protocol_ids(self) -> list[str]:
        """GET ``/protocols/ids`` and return id strings."""
        payload = await self._session.get_json("/protocols/ids")
        data = payload.get("data")
        if isinstance(data, list):
            return [str(item) for item in data]
        return []

    async def get_protocol(self, protocol_id: str) -> dict[str, Any]:
        """GET ``/protocols/{protocolId}``."""
        return await self._session.get_json(f"/protocols/{protocol_id}")

    async def upload_protocol(
        self,
        file_path: Path,
        *,
        protocol_kind: str = "standard",
        key: str | None = None,
        timeout: float = 120.0,
        expected_status: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        """POST multipart ``/protocols`` with one protocol file."""
        content = file_path.read_bytes()
        form: dict[str, str] = {"protocolKind": protocol_kind}
        if key is not None:
            form["key"] = key
        return await self._session.post_multipart(
            "/protocols",
            files=[
                (
                    "files",
                    (file_path.name, content, "application/octet-stream"),
                )
            ],
            form_fields=form,
            timeout=timeout,
            expected_status=expected_status or (200, 201),
        )

    async def delete_protocol(self, protocol_id: str) -> dict[str, Any]:
        """DELETE ``/protocols/{protocolId}``."""
        return await self._session.delete_json(
            f"/protocols/{protocol_id}",
            expected_status=(200, 204),
        )

    async def create_analysis(
        self,
        protocol_id: str,
        *,
        timeout: float = 120.0,
        expected_status: tuple[int, ...] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST ``/protocols/{protocolId}/analyses`` (reanalysis)."""
        return await self._session.post_json(
            f"/protocols/{protocol_id}/analyses",
            json_body={"data": {}},
            timeout=timeout,
            expected_status=expected_status or (201,),
            extra_headers=extra_headers,
        )

    async def list_analyses(self, protocol_id: str) -> list[dict[str, Any]]:
        """GET ``/protocols/{protocolId}/analyses``."""
        payload = await self._session.get_json(f"/protocols/{protocol_id}/analyses")
        return _data_list(payload)

    async def get_analysis(self, protocol_id: str, analysis_id: str) -> dict[str, Any]:
        """GET ``/protocols/{protocolId}/analyses/{analysisId}``."""
        return await self._session.get_json(
            f"/protocols/{protocol_id}/analyses/{analysis_id}"
        )

    async def get_analysis_document(self, protocol_id: str, analysis_id: str) -> bytes:
        """GET analysis as document bytes (may be plain text / JSON)."""
        content, _ = await self._session.get_bytes(
            f"/protocols/{protocol_id}/analyses/{analysis_id}/asDocument"
        )
        return content

    async def list_protocol_data_files(self, protocol_id: str) -> dict[str, Any]:
        """GET ``/protocols/{protocolId}/dataFiles``."""
        return await self._session.get_json(f"/protocols/{protocol_id}/dataFiles")

    def protocol_id_from_upload(self, payload: dict[str, Any]) -> str | None:
        """Extract protocol id from an upload / get envelope."""
        data = _data_object(payload)
        protocol_id = data.get("id")
        return str(protocol_id) if protocol_id is not None else None
