"""Auth-server settings client for access-control detection and enablement.

``PATCH /auth/settings/accessControlEnabled`` accepts only ``true`` and is
one-way. The harness exposes enable only via ``flex-test crs enable`` with an
explicit operator confirmation flag.
"""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.models.access_control import (
    AccessControlState,
    AccessControlStatus,
)


class AuthSettingsClient:
    """Atomic client for auth-server access-control detection.

    Source: ``auth-server/auth_server/settings/router.py``.
    """

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def get_access_control_enabled_raw(
        self, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Fetch raw access-control settings envelope."""
        return await self._session.get_json(
            "/auth/settings/accessControlEnabled",
            timeout=timeout,
        )

    async def detect_access_control(
        self, *, timeout: float | None = None
    ) -> AccessControlStatus:
        """Detect access-control state without mutating the robot.

        Missing endpoints or unexpected errors become ``unknown`` rather than
        inventing a value. HTTP 404 is reported as ``unsupported``.
        """
        try:
            payload = await self.get_access_control_enabled_raw(timeout=timeout)
        except RobotApiError as exc:
            if exc.status_code == 404:
                return AccessControlStatus(
                    state=AccessControlState.UNSUPPORTED,
                    detail="Access control endpoint not found (404).",
                )
            return AccessControlStatus(
                state=AccessControlState.UNKNOWN,
                detail=str(exc),
            )

        data = payload.get("data", payload)
        if not isinstance(data, dict) or "accessControlEnabled" not in data:
            return AccessControlStatus(
                state=AccessControlState.UNKNOWN,
                detail="Response missing accessControlEnabled field.",
            )

        enabled = bool(data["accessControlEnabled"])
        return AccessControlStatus(
            state=(
                AccessControlState.ENABLED if enabled else AccessControlState.DISABLED
            ),
            raw_enabled=enabled,
        )

    async def enable_access_control(
        self, *, timeout: float | None = None
    ) -> AccessControlStatus:
        """PATCH ``accessControlEnabled: true`` (one-way; CRS on).

        Callable without a bearer token while CRS is still off. After success,
        protected endpoints require OAuth scopes.
        """
        payload = await self._session.patch_json(
            "/auth/settings/accessControlEnabled",
            json_body={"data": {"accessControlEnabled": True}},
            timeout=timeout,
            expected_status=(200,),
        )
        data = payload.get("data", payload)
        if not isinstance(data, dict) or "accessControlEnabled" not in data:
            raise RobotApiError(
                "Response missing accessControlEnabled field.",
                status_code=200,
                path="/auth/settings/accessControlEnabled",
            )
        enabled = bool(data["accessControlEnabled"])
        return AccessControlStatus(
            state=(
                AccessControlState.ENABLED if enabled else AccessControlState.DISABLED
            ),
            raw_enabled=enabled,
        )
