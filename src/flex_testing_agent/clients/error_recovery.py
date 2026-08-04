"""Global error-recovery settings client (``/errorRecovery/settings``)."""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession


class ErrorRecoveryClient:
    """Atomic client for robot-wide error recovery enablement."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def get_settings(self) -> dict[str, Any]:
        """GET ``/errorRecovery/settings``."""
        return await self._session.get_json("/errorRecovery/settings")

    async def set_enabled(self, *, enabled: bool) -> dict[str, Any]:
        """PATCH ``/errorRecovery/settings``."""
        return await self._session.patch_json(
            "/errorRecovery/settings",
            json_body={"data": {"enabled": enabled}},
            expected_status=(200,),
        )

    def enabled_from_payload(self, payload: dict[str, Any]) -> bool | None:
        """Extract ``enabled`` from a settings envelope."""
        data = payload.get("data")
        if isinstance(data, dict) and "enabled" in data:
            return bool(data["enabled"])
        if "enabled" in payload:
            return bool(payload["enabled"])
        return None
