"""Robot-server health client (``GET /health``)."""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.models.health import HealthReport


class HealthClient:
    """Atomic client for robot-server health.

    Source: ``robot-server/robot_server/health/router.py``.
    """

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def get_health(self, *, timeout: float | None = None) -> HealthReport:
        """Fetch and normalize ``GET /health``."""
        payload = await self._session.get_json("/health", timeout=timeout)
        return HealthReport.model_validate(payload)

    async def get_health_raw(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Fetch raw ``GET /health`` JSON for evidence capture."""
        return await self._session.get_json("/health", timeout=timeout)
