"""Minimal live Flex smoke for Pyro subprocess validation.

Deck: Opentrons Flex 96 filter tiprack 50 uL in A1; rest clear.
Instrument: right flex_1channel_50 (P50 single).
Play homes the robot; use only with explicit operator approval.
"""

from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.20"}
metadata = {
    "protocolName": "pyro-live-p50-tip-smoke",
    "description": (
        "Minimal live pyro smoke: P50 single tip pickup/return "
        "from A1 filter tiprack"
    ),
}


def run(protocol: protocol_api.ProtocolContext) -> None:
    tiprack = protocol.load_labware("opentrons_flex_96_filtertiprack_50ul", "A1")
    pipette = protocol.load_instrument(
        "flex_1channel_50",
        "right",
        tip_racks=[tiprack],
    )
    protocol.comment("pick up tip from A1 tiprack")
    pipette.pick_up_tip()
    protocol.comment("return tip to rack (no trash required)")
    pipette.return_tip()
    protocol.comment("pyro live tip smoke complete")
