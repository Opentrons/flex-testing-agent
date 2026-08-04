"""KansasFLEX seed: simple home + move (no tips, dry deck).

Deck: trash A3; heater-shaker D1; otherwise clear.
Instrument: right flex_1channel_50.
Tip detection unused (no tip pickup). Sensing off via robot settings preferred.
"""

from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.20"}
metadata = {
    "protocolName": "seed-simple-home-move",
    "description": "Seed history: home + move to trash top (right P50, no tips)",
}


def run(protocol: protocol_api.ProtocolContext) -> None:
    trash = protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument("flex_1channel_50", "right")
    protocol.comment("seed-simple: home")
    protocol.home()
    protocol.comment("seed-simple: move to trash top")
    pipette.move_to(trash.top())
    protocol.comment("seed-simple: home again")
    protocol.home()
    protocol.comment("seed-simple: complete")
