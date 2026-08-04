"""KansasFLEX seed: complex dry moves with both pipettes (no tips).

Deck: trash A3; HS D1; clear otherwise.
Uses comments, delays, and multi-instrument moves (no pick_up_tip).
"""

from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.20"}
metadata = {
    "protocolName": "seed-complex-dry-moves",
    "description": "Seed history: both P50s move to trash tops with delays/comments",
}


def run(protocol: protocol_api.ProtocolContext) -> None:
    trash = protocol.load_trash_bin("A3")
    right = protocol.load_instrument("flex_1channel_50", "right")
    left = protocol.load_instrument("flex_8channel_50", "left")
    protocol.comment("seed-complex: home")
    protocol.home()
    protocol.comment("seed-complex: right to trash")
    right.move_to(trash.top(z=10))
    protocol.delay(seconds=1)
    protocol.comment("seed-complex: left to trash")
    left.move_to(trash.top(z=20))
    protocol.delay(seconds=1)
    protocol.comment("seed-complex: right approach again")
    right.move_to(trash.top(z=5))
    protocol.comment("seed-complex: home")
    protocol.home()
    protocol.comment("seed-complex: complete")
