"""KansasFLEX seed: heater-shaker at API min temp + short shake.

Module: heaterShakerModuleV1 in D1. Protocol API min HS target is 37 C
(not ambient). Shake < 5 seconds. No tip pickup. Empty deck except
module + trash A3.
"""

from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.20"}
metadata = {
    "protocolName": "seed-heater-shaker-brief",
    "description": "Seed history: HS 37C (API min) + shake <5s, then deactivate",
}


def run(protocol: protocol_api.ProtocolContext) -> None:
    hs = protocol.load_module("heaterShakerModuleV1", "D1")
    protocol.comment("seed-hs: close latch")
    hs.close_labware_latch()
    # Valid HS range is 37-95 C; 23 C was rejected by the API.
    protocol.comment("seed-hs: set target 37C (API minimum)")
    hs.set_target_temperature(37)
    hs.wait_for_temperature()
    protocol.comment("seed-hs: shake ~3s at 200 rpm")
    hs.set_and_wait_for_shake_speed(200)
    protocol.delay(seconds=3)
    protocol.comment("seed-hs: deactivate shaker and heater")
    hs.deactivate_shaker()
    hs.deactivate_heater()
    protocol.comment("seed-hs: open latch")
    hs.open_labware_latch()
    protocol.comment("seed-hs: complete")
