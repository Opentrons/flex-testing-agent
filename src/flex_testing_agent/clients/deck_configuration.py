"""Deck configuration client.

Source: ``robot-server`` ``/deck_configuration``.
"""

from __future__ import annotations

from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession

# KansasFLEX lab baseline (HS on D1, trash A3). Serial filled at apply time.
KANSAS_DECK_CUTOUTS_TEMPLATE: list[dict[str, str]] = [
    {"cutoutFixtureId": "singleLeftSlot", "cutoutId": "cutoutA1"},
    {"cutoutFixtureId": "singleLeftSlot", "cutoutId": "cutoutB1"},
    {"cutoutFixtureId": "singleLeftSlot", "cutoutId": "cutoutC1"},
    {
        "cutoutFixtureId": "heaterShakerModuleV1",
        "cutoutId": "cutoutD1",
        "opentronsModuleSerialNumber": "",
    },
    {"cutoutFixtureId": "singleCenterSlot", "cutoutId": "cutoutA2"},
    {"cutoutFixtureId": "singleCenterSlot", "cutoutId": "cutoutB2"},
    {"cutoutFixtureId": "singleCenterSlot", "cutoutId": "cutoutC2"},
    {"cutoutFixtureId": "singleCenterSlot", "cutoutId": "cutoutD2"},
    {"cutoutFixtureId": "trashBinAdapter", "cutoutId": "cutoutA3"},
    {"cutoutFixtureId": "singleRightSlot", "cutoutId": "cutoutB3"},
    {"cutoutFixtureId": "singleRightSlot", "cutoutId": "cutoutC3"},
    {"cutoutFixtureId": "singleRightSlot", "cutoutId": "cutoutD3"},
]


class DeckConfigurationClient:
    """Atomic client for ``/deck_configuration``."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def get(self) -> dict[str, Any]:
        """GET ``/deck_configuration``."""
        return await self._session.get_json("/deck_configuration")

    async def put(self, cutout_fixtures: list[dict[str, Any]]) -> dict[str, Any]:
        """PUT ``/deck_configuration`` with cutoutFixtures list."""
        return await self._session.put_json(
            "/deck_configuration",
            json_body={"data": {"cutoutFixtures": cutout_fixtures}},
            expected_status=(200,),
        )


def kansas_deck_cutouts(*, heater_shaker_serial: str) -> list[dict[str, str]]:
    """Return the KansasFLEX baseline deck cutouts with HS serial filled in."""
    cutouts: list[dict[str, str]] = []
    for item in KANSAS_DECK_CUTOUTS_TEMPLATE:
        row = dict(item)
        if row.get("cutoutFixtureId") == "heaterShakerModuleV1":
            row["opentronsModuleSerialNumber"] = heater_shaker_serial
        elif (
            "opentronsModuleSerialNumber" in row
            and not row["opentronsModuleSerialNumber"]
        ):
            row.pop("opentronsModuleSerialNumber", None)
        cutouts.append(row)
    return cutouts
