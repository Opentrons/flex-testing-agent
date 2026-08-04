"""KansasFLEX seed: intentional protocol failure for failed-run history.

Raises after a short dry comment so the run terminates as ``failed``.
"""

from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.20"}
metadata = {
    "protocolName": "seed-failed-intentional",
    "description": "Seed history: intentional RuntimeError for failed terminal status",
}


def run(protocol: protocol_api.ProtocolContext) -> None:
    protocol.comment("seed-failed: begin intentional failure")
    protocol.home()
    protocol.comment("seed-failed: raising")
    raise RuntimeError("flex-testing-agent intentional seed failure")
