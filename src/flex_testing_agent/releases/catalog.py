"""Parse Flex ``ot3-oe/releases.json`` manifests into lane summaries.

Parsing rules follow ``Opentrons/robot-stack``:

- ``automation/release.py`` (``robot_manifest_production_entries``,
  ``RobotReleasesCollection``)
- ``automation/flex_assets.py`` (manifest locations)
"""

from __future__ import annotations

from typing import Any

from packaging.version import Version
from pydantic import BaseModel, Field

from flex_testing_agent.releases.urls import ReleaseChannel
from flex_testing_agent.releases.versions import (
    ReleaseStability,
    classify_stability,
    normalize_robot_version,
    parse_version,
    stack_tag_for_version,
)


class RobotReleaseEntry(BaseModel):
    """One robot OS release from ``ot3-oe/releases.json``."""

    version: str
    stability: ReleaseStability
    stack_tag: str | None = None
    full_image: str | None = None
    system: str | None = None
    version_url: str | None = None
    release_notes: str | None = None
    manifest_bucket: str | None = None


class LatestByStability(BaseModel):
    """Newest release per stability lane."""

    stable: RobotReleaseEntry | None = None
    alpha: RobotReleaseEntry | None = None
    beta: RobotReleaseEntry | None = None


class FlexReleaseCatalog(BaseModel):
    """Parsed robot OS catalog for one internal or external channel."""

    channel: ReleaseChannel
    manifest_url: str
    entries: list[RobotReleaseEntry] = Field(default_factory=list)
    latest: LatestByStability = Field(default_factory=LatestByStability)
    error: str | None = None


class FlexReleaseSummary(BaseModel):
    """Latest internal and external Flex robot OS releases."""

    internal: FlexReleaseCatalog
    external: FlexReleaseCatalog


def merge_production_entries(
    manifest: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], str]]:
    """Merge ``production`` and ``productionV2`` with V2 winning on duplicates.

    Flex publishes newer builds under ``productionV2`` so pre-9.1.1 robots keep
    reading the legacy ``production`` key (robot-stack ``release.py``).
    """
    legacy = manifest.get("production", {})
    v2 = manifest.get("productionV2", {})
    if not isinstance(legacy, dict):
        legacy = {}
    if not isinstance(v2, dict):
        v2 = {}

    merged: dict[str, tuple[dict[str, Any], str]] = {}
    for version, info in legacy.items():
        if isinstance(info, dict):
            merged[str(version)] = (info, "production")
    for version, info in v2.items():
        if isinstance(info, dict):
            merged[str(version)] = (info, "productionV2")
    return merged


def build_catalog(
    *,
    channel: ReleaseChannel,
    manifest_url: str,
    manifest: dict[str, Any],
) -> FlexReleaseCatalog:
    """Build a catalog from a fetched robot releases.json payload."""
    entries: list[RobotReleaseEntry] = []
    for version, (info, bucket) in merge_production_entries(manifest).items():
        stability = classify_stability(version)
        if stability is None:
            continue
        entries.append(
            RobotReleaseEntry(
                version=version,
                stability=stability,
                stack_tag=stack_tag_for_version(version, channel),
                full_image=info.get("fullImage"),
                system=info.get("system"),
                version_url=info.get("version"),
                release_notes=info.get("releaseNotes"),
                manifest_bucket=bucket,
            )
        )

    latest = summarize_latest(entries)
    return FlexReleaseCatalog(
        channel=channel,
        manifest_url=manifest_url,
        entries=entries,
        latest=latest,
    )


def summarize_latest(entries: list[RobotReleaseEntry]) -> LatestByStability:
    """Return the newest entry per stability lane using packaging Version order."""

    def _version_key(entry: RobotReleaseEntry) -> Version:
        return parse_version(entry.version) or Version("0")

    def _newest(stability: ReleaseStability) -> RobotReleaseEntry | None:
        candidates = [e for e in entries if e.stability == stability]
        if not candidates:
            return None
        return max(candidates, key=_version_key)

    return LatestByStability(
        stable=_newest(ReleaseStability.STABLE),
        alpha=_newest(ReleaseStability.ALPHA),
        beta=_newest(ReleaseStability.BETA),
    )


def find_entry(catalog: FlexReleaseCatalog, version: str) -> RobotReleaseEntry | None:
    """Find a catalog entry matching a robot/health version string."""
    normalized = normalize_robot_version(version)
    if normalized is None:
        return None
    for entry in catalog.entries:
        if entry.version == normalized:
            return entry
    return None
