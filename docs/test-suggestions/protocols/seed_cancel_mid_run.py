"""KansasFLEX seed: long-enough motion so harness can cancel mid-run.

Harness plays then POST stop after first motion / delay starts.
"""

from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.20"}
metadata = {
    "protocolName": "seed-cancel-mid-run",
    "description": "Seed history: intentional long dry sequence for mid-run cancel",
}


def run(protocol: protocol_api.ProtocolContext) -> None:
    trash = protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument("flex_1channel_50", "right")
    protocol.comment("seed-cancel: home")
    protocol.home()
    for idx in range(1, 9):
        protocol.comment(f"seed-cancel: loop {idx} to trash")
        pipette.move_to(trash.top(z=5 + idx))
        protocol.delay(seconds=2)
    protocol.comment("seed-cancel: should not reach if cancelled")
    protocol.home()
