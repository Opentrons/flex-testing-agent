"""Client-data key/value store (``/clientData``).

Source: ``robot-server/robot_server/client_data/router.py``.
In-memory App/ODD coordination; cleared on robot-server reboot. Not under CRS:
PUT/DELETE succeed with no token even when access control is on (RQA-5918,
expected). Safe for reversible Tier C mutations.
"""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession


class ClientDataClient:
    """Atomic client for ``/clientData/{key}``."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def get(self, key: str) -> dict[str, Any]:
        """GET ``/clientData/{key}``."""
        return await self._session.get_json(f"/clientData/{key}")

    async def put(self, key: str, data: dict[str, Any]) -> dict[str, Any]:
        """PUT ``/clientData/{key}`` with a JSON-API body."""
        return await self._session.put_json(
            f"/clientData/{key}",
            json_body={"data": data},
        )

    async def delete(self, key: str) -> dict[str, Any]:
        """DELETE ``/clientData/{key}``."""
        return await self._session.delete_json(
            f"/clientData/{key}",
            expected_status=(200, 204),
        )

    async def delete_all(self) -> dict[str, Any]:
        """DELETE ``/clientData`` (clear all keys)."""
        return await self._session.delete_json(
            "/clientData",
            expected_status=(200, 204),
        )
