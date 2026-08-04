"""Lightweight robot control client (lights only for CRS-off Tier C).

Source: ``robot-server/robot_server/service/legacy/routers/control.py``.

Home / move / identify stay out of this client; physical motion remains
gated at the capability layer.
"""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession


class RobotControlClient:
    """Atomic client for safe robot control reads/writes."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def get_lights(self) -> dict[str, Any]:
        """GET ``/robot/lights``."""
        return await self._session.get_json("/robot/lights")

    async def set_lights(self, *, on: bool) -> dict[str, Any]:
        """POST ``/robot/lights`` with ``{"on": bool}``."""
        return await self._session.post_json(
            "/robot/lights",
            json_body={"on": on},
        )

    async def get_estop_status(self) -> dict[str, Any]:
        """GET ``/robot/control/estopStatus``."""
        return await self._session.get_json("/robot/control/estopStatus")

    async def get_door_status(self) -> dict[str, Any]:
        """GET ``/robot/door/status``."""
        return await self._session.get_json("/robot/door/status")
