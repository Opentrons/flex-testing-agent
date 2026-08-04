"""Subsystem firmware status and update client."""

from __future__ import annotations

import asyncio
from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession


class SubsystemsClient:
    """Atomic client for ``/subsystems/status`` and ``/subsystems/updates``."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def list_status(self) -> list[dict[str, Any]]:
        """GET ``/subsystems/status`` data list."""
        payload = await self._session.get_json("/subsystems/status")
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    async def subsystems_needing_update(self) -> list[str]:
        """Return subsystem names with ``fw_update_needed`` true."""
        names: list[str] = []
        for item in await self.list_status():
            if item.get("fw_update_needed") is True and item.get("name"):
                names.append(str(item["name"]))
        return names

    async def start_update(self, subsystem: str) -> dict[str, Any]:
        """POST ``/subsystems/updates/{subsystem}``.

        Robot may respond ``201`` with the update body, or ``303 See Other``
        with a ``Location`` to the update resource (treat as success).
        """
        return await self._session.post_json(
            f"/subsystems/updates/{subsystem}",
            json_body={},
            expected_status=(200, 201, 303),
        )

    async def get_update(self, update_id: str) -> dict[str, Any]:
        """GET ``/subsystems/updates/all/{id}``."""
        return await self._session.get_json(f"/subsystems/updates/all/{update_id}")

    async def list_current_updates(self) -> dict[str, Any]:
        """GET ``/subsystems/updates/current``."""
        return await self._session.get_json("/subsystems/updates/current")

    async def current_update_summaries(self) -> list[dict[str, Any]]:
        """Return in-flight / queued subsystem update objects."""
        payload = await self.list_current_updates()
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    async def wait_until_firmware_idle(
        self,
        *,
        timeout_seconds: float = 900.0,
        poll_interval_seconds: float = 3.0,
    ) -> list[dict[str, Any]]:
        """Wait until no FW update is needed and no updates are in flight."""
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        last = await self.list_status()
        while asyncio.get_running_loop().time() < deadline:
            last = await self.list_status()
            needing = [
                str(item.get("name"))
                for item in last
                if item.get("fw_update_needed") is True
            ]
            current = await self.current_update_summaries()
            if not needing and not current:
                return last
            await asyncio.sleep(poll_interval_seconds)
        still_current = await self.current_update_summaries()
        still_need = [
            str(item.get("name"))
            for item in last
            if item.get("fw_update_needed") is True
        ]
        raise TimeoutError(
            "Timed out waiting for subsystem FW updates; "
            f"needed={still_need} in_flight={still_current}"
        )
