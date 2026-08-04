"""KansasFLEX seed: comments + Protocol API capture_image + short motion.

Uses ``protocol.capture_image`` (API ≥ 2.27) so images are stored on the run.
Harness may also POST /camera/picture while the run is current.
"""

from opentrons import protocol_api

requirements = {"robotType": "Flex", "apiLevel": "2.27"}
metadata = {
    "protocolName": "seed-camera-and-comments",
    "description": (
        "Seed history: comments + capture_image + short dry moves "
        "(in-protocol camera API)"
    ),
}


def run(protocol: protocol_api.ProtocolContext) -> None:
    trash = protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument("flex_1channel_50", "right")
    protocol.comment("seed-camera: begin — in-protocol capture_image + comments")
    protocol.home()
    protocol.comment("seed-camera: capture after home")
    protocol.capture_image(
        home_before=False,
        filename="seed_camera_after_home",
        resolution=(1280, 720),
    )
    protocol.comment("seed-camera: move 1")
    pipette.move_to(trash.top(z=15))
    protocol.delay(seconds=2)
    protocol.comment("seed-camera: capture mid-run")
    protocol.capture_image(
        home_before=True,
        filename="seed_camera_mid_run",
        zoom=1.0,
    )
    protocol.comment("seed-camera: move 2")
    pipette.move_to(trash.top(z=8))
    protocol.delay(seconds=2)
    protocol.comment("seed-camera: final capture")
    protocol.capture_image(filename="seed_camera_final")
    protocol.comment("seed-camera: home and complete")
    protocol.home()
