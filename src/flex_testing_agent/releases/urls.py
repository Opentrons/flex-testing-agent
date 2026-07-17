"""Flex release manifest URL constants.

Authoritative definitions live in Opentrons/robot-stack:

- ``automation/flex_urls.py``
- ``automation/asset_urls.py``
- ``automation/flex_assets.py``
"""

from __future__ import annotations

from enum import StrEnum

FLEX_ROBOT_PREFIX = "ot3-oe"
FLEX_APP_PREFIX = "app"

FLEX_EXTERNAL_HOST = "builds.opentrons.com"
FLEX_INTERNAL_HOST = "ot3-development.builds.opentrons.com"


class ReleaseChannel(StrEnum):
    """Internal vs external Flex release pipeline."""

    INTERNAL = "internal"
    EXTERNAL = "external"


def robot_releases_json_url(channel: ReleaseChannel) -> str:
    """Return the robot OS ``ot3-oe/releases.json`` URL for a channel.

    Flex robots use this manifest as the source of truth for on-robot updates.
    """
    host = (
        FLEX_INTERNAL_HOST if channel == ReleaseChannel.INTERNAL else FLEX_EXTERNAL_HOST
    )
    return f"https://{host}/{FLEX_ROBOT_PREFIX}/releases.json"


def app_releases_json_url(channel: ReleaseChannel) -> str:
    """Return the desktop app ``app/releases.json`` URL for a channel."""
    host = (
        FLEX_INTERNAL_HOST if channel == ReleaseChannel.INTERNAL else FLEX_EXTERNAL_HOST
    )
    return f"https://{host}/{FLEX_APP_PREFIX}/releases.json"
