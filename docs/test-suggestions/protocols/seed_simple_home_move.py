"""KansasFLEX seed: simple home + move (no tips, dry deck).

Deck: trash A3; heater-shaker D1; otherwise clear.
Instrument: right flex_1channel_50.
Tip detection unused (no tip pickup). Sensing off via robot settings preferred.

Uses ``group_steps`` (API 2.29+) so the run stores real ``commandAnnotations``
for CRS-off Tier B ``/runs/{runId}/commandAnnotations/{commandAnnotationId}``.
"""

from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.29"}
metadata = {
    "protocolName": "seed-simple-home-move",
    "description": (
        "Seed history: home + move to trash top (right P50, no tips); "
        "group_steps for commandAnnotations fixture"
    ),
}


def run(protocol: protocol_api.ProtocolContext) -> None:
    trash = protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument("flex_1channel_50", "right")
    protocol.comment("seed-simple: home")
    protocol.home()
    protocol.comment("seed-simple: grouped move to trash top")
    with protocol.group_steps(
        "seed-simple-move",
        "flex-testing-agent Tier B commandAnnotations fixture",
    ):
        pipette.move_to(trash.top())
    protocol.comment("seed-simple: home again")
    protocol.home()
    protocol.comment("seed-simple: complete")
