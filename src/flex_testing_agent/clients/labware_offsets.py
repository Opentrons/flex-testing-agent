"""Stored labware offset client (``/labwareOffsets``).

Source: ``robot-server`` Labware Offset Management routes. Used to persist
offsets produced by scripted LPC / maintenance-run jog flows.
"""

from __future__ import annotations

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


class LabwareOffsetsClient:
    """Atomic client for robot-stored labware offsets."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def list_offsets(self) -> dict[str, Any]:
        """GET ``/labwareOffsets``."""
        return await self._session.get_json("/labwareOffsets")

    async def list_offset_summaries(self) -> list[dict[str, Any]]:
        """Return offset objects from ``GET /labwareOffsets``."""
        return _data_list(await self.list_offsets())

    async def create_offset(self, offset: dict[str, Any]) -> dict[str, Any]:
        """POST ``/labwareOffsets`` with one ``StoredLabwareOffsetCreate``."""
        return await self._session.post_json(
            "/labwareOffsets",
            json_body={"data": offset},
            expected_status=(200, 201),
        )

    async def create_offsets(self, offsets: list[dict[str, Any]]) -> dict[str, Any]:
        """POST ``/labwareOffsets`` with a list of creates."""
        return await self._session.post_json(
            "/labwareOffsets",
            json_body={"data": offsets},
            expected_status=(200, 201),
        )

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST ``/labwareOffsets/searches``."""
        return await self._session.post_json(
            "/labwareOffsets/searches",
            json_body=body,
            expected_status=(200, 201),
        )

    async def delete_all(self) -> dict[str, Any]:
        """DELETE ``/labwareOffsets``."""
        return await self._session.delete_json(
            "/labwareOffsets",
            expected_status=(200, 204),
        )

    async def delete_one(self, offset_id: str) -> dict[str, Any]:
        """DELETE ``/labwareOffsets/{id}``."""
        return await self._session.delete_json(
            f"/labwareOffsets/{offset_id}",
            expected_status=(200, 204),
        )

    def offset_id_from_create(self, payload: dict[str, Any]) -> str | None:
        """Extract created offset id (single-object create response)."""
        data = payload.get("data")
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"])
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and first.get("id"):
                return str(first["id"])
        obj = _data_object(payload)
        oid = obj.get("id")
        return str(oid) if oid else None
