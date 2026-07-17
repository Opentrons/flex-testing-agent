"""Update-server health client (``GET /server/update/health``)."""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.models.health import UpdateHealthReport


class UpdateHealthClient:
    """Atomic client for update-server health.

    Source: ``update-server/otupdate/openembedded/__init__.py``.
    """

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def get_update_health(
        self, *, timeout: float | None = None
    ) -> UpdateHealthReport:
        """Fetch and normalize ``GET /server/update/health``."""
        payload = await self._session.get_json("/server/update/health", timeout=timeout)
        return UpdateHealthReport.model_validate(payload)

    async def get_update_health_raw(
        self, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Fetch raw update health JSON for evidence capture."""
        return await self._session.get_json("/server/update/health", timeout=timeout)
