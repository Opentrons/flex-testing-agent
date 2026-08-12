"""Instruments inventory client."""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession


class InstrumentsClient:
    """Atomic client for ``GET /instruments``."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def list_instruments(self) -> dict[str, Any]:
        """GET ``/instruments`` envelope."""
        return await self._session.get_json("/instruments")

    async def list_instrument_summaries(self) -> list[dict[str, Any]]:
        """Return instrument data objects from ``GET /instruments``."""
        payload = await self.list_instruments()
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]
