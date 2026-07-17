"""Flex version / tag helpers aligned with robot-stack tagging rules.

Source: ``Opentrons/robot-stack`` README and ``automation/release_tag_catalog.py``.

Internal stack tags use ``ot3@X.Y.Z`` / ``ot3@X.Y.Z-alpha.N`` / ``ot3@X.Y.Z-beta.N``.
External stack tags use ``vX.Y.Z`` / ``vX.Y.Z-alpha.N`` / ``vX.Y.Z-beta.N``.
Robot ``releases.json`` keys are the bare semver without the ``ot3@`` or ``v`` prefix.
"""

from __future__ import annotations

import re
from enum import StrEnum

from packaging.version import InvalidVersion, Version

from flex_testing_agent.releases.urls import ReleaseChannel


class ReleaseStability(StrEnum):
    """Stability lane within a Flex release channel."""

    STABLE = "stable"
    ALPHA = "alpha"
    BETA = "beta"


_SEMVER_RE = re.compile(
    r"^(?P<base>\d+\.\d+\.\d+)(?:-(?P<pre>alpha|beta)\.(?P<pre_n>\d+))?$"
)


def normalize_robot_version(value: str) -> str | None:
    """Normalize a robot OS / health version string to a bare semver key.

    Accepts bare keys (``4.0.0-alpha.5``), internal tags (``ot3@...``), and
    external tags (``v...``). Returns None when the shape is not a Flex
    coordinated semver release.
    """
    cleaned = value.strip()
    if cleaned.startswith("ot3@"):
        cleaned = cleaned.removeprefix("ot3@")
    elif cleaned.startswith("v") and re.match(r"^v\d", cleaned):
        cleaned = cleaned[1:]
    if _SEMVER_RE.match(cleaned):
        return cleaned
    return None


def classify_stability(version: str) -> ReleaseStability | None:
    """Return alpha/beta/stable for a bare Flex robot version key."""
    normalized = normalize_robot_version(version)
    if normalized is None:
        return None
    match = _SEMVER_RE.match(normalized)
    if match is None:
        return None
    pre = match.group("pre")
    if pre == "alpha":
        return ReleaseStability.ALPHA
    if pre == "beta":
        return ReleaseStability.BETA
    return ReleaseStability.STABLE


def stack_tag_for_version(version: str, channel: ReleaseChannel) -> str | None:
    """Map a robot manifest version key to the coordinated stack tag."""
    normalized = normalize_robot_version(version)
    if normalized is None:
        return None
    if channel == ReleaseChannel.INTERNAL:
        return f"ot3@{normalized}"
    return f"v{normalized}"


def parse_version(version: str) -> Version | None:
    """Parse a Flex version key with packaging.version."""
    normalized = normalize_robot_version(version)
    if normalized is None:
        return None
    try:
        return Version(normalized)
    except InvalidVersion:
        return None
