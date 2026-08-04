"""KansasFLEX seed: analyzed protocol only (harness creates current idle run).

No motion when played is not the point — harness creates a run and does not play.
"""

from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.20"}
metadata = {
    "protocolName": "seed-idle-current",
    "description": "Seed history: minimal protocol for a never-played current idle run",
}


def run(protocol: protocol_api.ProtocolContext) -> None:
    protocol.load_trash_bin("A3")
    protocol.load_instrument("flex_1channel_50", "right")
    protocol.comment("seed-idle: not played; current idle fixture only")
