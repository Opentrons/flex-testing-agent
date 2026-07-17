"""Flex robot implementation for Kansas and similar Flex targets."""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.auth_settings import AuthSettingsClient
from flex_testing_agent.clients.camera import CameraClient
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.health import HealthClient
from flex_testing_agent.clients.modules import ModulesClient
from flex_testing_agent.clients.readonly import ReadonlyClient
from flex_testing_agent.clients.session import RobotHttpSession
from flex_testing_agent.clients.update import UpdateClient
from flex_testing_agent.clients.update_health import UpdateHealthClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.access_control import (
    AccessControlState,
    AccessControlStatus,
)
from flex_testing_agent.models.health import HealthReport, UpdateHealthReport
from flex_testing_agent.models.snapshot import RobotSnapshot


class FlexRobot:
    """Opentrons Flex robot under test.

    Dual-mode ready: ``access_token`` may be supplied when access control is
    enabled. Inspect does not require credentials when access control is off.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        session: RobotHttpSession | None = None,
        access_token: str | None = None,
    ) -> None:
        self.settings = settings
        self._owns_session = session is None
        self._session = session or RobotHttpSession(
            settings.robot_base_url,
            timeout_seconds=settings.robot_request_timeout_seconds,
            access_token=access_token,
        )
        self.health = HealthClient(self._session)
        self.update_health = UpdateHealthClient(self._session)
        self.auth_settings = AuthSettingsClient(self._session)
        self.update = UpdateClient(self._session)
        self.camera = CameraClient(self._session)
        self.readonly = ReadonlyClient(self._session)
        self.modules = ModulesClient(self._session)
        self._raw_evidence: dict[str, Any] = {}

    @property
    def session(self) -> RobotHttpSession:
        """Shared HTTP session for atomic clients."""
        return self._session

    @property
    def raw_evidence(self) -> dict[str, Any]:
        """Raw API payloads collected during recent operations."""
        return self._raw_evidence

    async def aclose(self) -> None:
        """Close owned HTTP session."""
        if self._owns_session:
            await self._session.aclose()

    async def __aenter__(self) -> FlexRobot:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def verify_health(self) -> HealthReport:
        """Query ``GET /health`` with the health timeout."""
        return await self.health.get_health(
            timeout=self.settings.robot_health_timeout_seconds
        )

    async def inspect(self) -> RobotSnapshot:
        """Collect health, update health, and access-control detection."""
        errors: list[str] = []
        self._raw_evidence = {}
        health: HealthReport | None = None
        update_health: UpdateHealthReport | None = None
        connectivity = False

        try:
            raw_health = await self.health.get_health_raw(
                timeout=self.settings.robot_health_timeout_seconds
            )
            self._raw_evidence["health"] = raw_health
            health = HealthReport.model_validate(raw_health)
            connectivity = True
        except RobotApiError as exc:
            errors.append(f"health: {exc}")

        try:
            raw_update = await self.update_health.get_update_health_raw(
                timeout=self.settings.robot_request_timeout_seconds
            )
            self._raw_evidence["update_health"] = raw_update
            update_health = UpdateHealthReport.model_validate(raw_update)
            connectivity = True
        except RobotApiError as exc:
            errors.append(f"update_health: {exc}")

        access_control = await self._detect_access_control(errors)

        return RobotSnapshot(
            configured_name=self.settings.robot_name,
            host=self.settings.require_robot_host(),
            base_url=self.settings.robot_base_url,
            connectivity=connectivity,
            health=health,
            update_health=update_health,
            access_control=access_control,
            errors=errors,
        )

    async def _detect_access_control(self, errors: list[str]) -> AccessControlStatus:
        """Detect access control without enabling it."""
        try:
            raw_ac = await self.auth_settings.get_access_control_enabled_raw(
                timeout=self.settings.robot_request_timeout_seconds
            )
            self._raw_evidence["access_control"] = raw_ac
            data = raw_ac.get("data", raw_ac)
            if not isinstance(data, dict) or "accessControlEnabled" not in data:
                return AccessControlStatus(
                    state=AccessControlState.UNKNOWN,
                    detail="Response missing accessControlEnabled field.",
                )
            enabled = bool(data["accessControlEnabled"])
            return AccessControlStatus(
                state=(
                    AccessControlState.ENABLED
                    if enabled
                    else AccessControlState.DISABLED
                ),
                raw_enabled=enabled,
            )
        except RobotApiError as exc:
            errors.append(f"access_control: {exc}")
            if exc.status_code == 404:
                return AccessControlStatus(
                    state=AccessControlState.UNSUPPORTED,
                    detail="Access control endpoint not found (404).",
                )
            return AccessControlStatus(
                state=AccessControlState.UNKNOWN,
                detail=str(exc),
            )
