"""Robot advanced settings client (``GET/POST /settings``)."""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession

DISABLE_STALL_DETECTION = "disableStallDetection"
DISABLE_OVERPRESSURE_DETECTION = "disableOverpressureDetection"


class RobotSettingsClient:
    """Atomic client for robot advanced settings."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def get_settings(self) -> dict[str, Any]:
        """GET ``/settings``."""
        return await self._session.get_json("/settings")

    async def set_setting(self, setting_id: str, value: bool | None) -> dict[str, Any]:
        """POST ``/settings`` to set one advanced setting."""
        return await self._session.post_json(
            "/settings",
            json_body={"id": setting_id, "value": value},
            expected_status=(200,),
        )

    async def setting_value(self, setting_id: str) -> bool | None:
        """Return current value for ``setting_id`` if present."""
        payload = await self.get_settings()
        settings = payload.get("settings")
        if not isinstance(settings, list):
            return None
        for item in settings:
            if isinstance(item, dict) and item.get("id") == setting_id:
                raw = item.get("value")
                if raw is None:
                    return None
                return bool(raw)
        return None
