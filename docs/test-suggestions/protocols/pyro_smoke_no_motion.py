"""Analysis / create-run smoke with no labware and no intentional motion.

Analysis may still emit a simulated home command in the analysis document.
Do not press Play unless the operator accepts a real home.
"""

from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.20"}
metadata = {"protocolName": "pyro-smoke-no-motion"}


def run(protocol: protocol_api.ProtocolContext) -> None:
    protocol.comment("pyro subprocess smoke; no labware, no motion")
