"""Robot settings reset client (factory / robot-server data wipe).

Source: ``robot-server`` ``POST /settings/reset``, ``GET /settings/reset/options``.

Never clear ``authorizedKeys`` unless the caller explicitly opts in.
"""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession

# Option ids from GET /settings/reset/options on Flex 4.x / 9.x.
RUNS_HISTORY = "runsHistory"
DECK_CONFIGURATION = "deckConfiguration"
ON_DEVICE_DISPLAY = "onDeviceDisplay"
MODULE_CALIBRATION = "moduleCalibration"
PIPETTE_OFFSET = "pipetteOffsetCalibrations"
GRIPPER_OFFSET = "gripperOffsetCalibrations"
BOOT_SCRIPTS = "bootScripts"
AUTHORIZED_KEYS = "authorizedKeys"

DEFAULT_DATA_RESET: frozenset[str] = frozenset({RUNS_HISTORY})


class SettingsResetClient:
    """Atomic client for listing and applying settings reset options."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def list_options(self) -> dict[str, Any]:
        """GET ``/settings/reset/options``."""
        return await self._session.get_json("/settings/reset/options")

    async def reset(self, options: dict[str, bool]) -> dict[str, Any]:
        """POST ``/settings/reset`` with a map of option id → true."""
        return await self._session.post_json(
            "/settings/reset",
            json_body=options,
            expected_status=(200,),
        )

    async def reset_selected(
        self, option_ids: set[str] | frozenset[str]
    ) -> dict[str, Any]:
        """Reset the given option ids (values set to True)."""
        body = {option_id: True for option_id in sorted(option_ids)}
        return await self.reset(body)
