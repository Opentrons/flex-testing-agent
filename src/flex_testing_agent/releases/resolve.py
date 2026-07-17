"""Resolve a Flex version string to a published BuildArtifact."""

from __future__ import annotations

from flex_testing_agent.models.build import BuildArtifact
from flex_testing_agent.releases.catalog import find_entry
from flex_testing_agent.releases.client import fetch_channel_catalog
from flex_testing_agent.releases.urls import ReleaseChannel
from flex_testing_agent.releases.versions import normalize_robot_version


class BuildNotFoundError(LookupError):
    """Raised when a version is not present in published releases.json catalogs."""


async def resolve_build(
    version: str,
    *,
    channel: ReleaseChannel | None = None,
    timeout_seconds: float = 30.0,
) -> BuildArtifact:
    """Resolve ``version`` to a robot OS system.zip artifact.

    Searches external then internal unless ``channel`` is set. Prefer external
    for customer-facing ``9.x`` alphas/betas/stables.
    """
    normalized = normalize_robot_version(version)
    if normalized is None:
        raise BuildNotFoundError(
            f"{version!r} is not a Flex coordinated semver version."
        )

    channels = (
        [channel]
        if channel is not None
        else [ReleaseChannel.EXTERNAL, ReleaseChannel.INTERNAL]
    )
    errors: list[str] = []
    for candidate in channels:
        catalog = await fetch_channel_catalog(
            candidate, timeout_seconds=timeout_seconds
        )
        if catalog.error:
            errors.append(f"{candidate.value}: {catalog.error}")
            continue
        entry = find_entry(catalog, normalized)
        if entry is None:
            errors.append(f"{candidate.value}: version not in catalog")
            continue
        if not entry.system:
            raise BuildNotFoundError(
                f"{normalized} found in {candidate.value} but missing system URL."
            )
        return BuildArtifact(
            version=entry.version,
            channel=candidate,
            stability=entry.stability,
            stack_tag=entry.stack_tag,
            system_url=entry.system,
            full_image_url=entry.full_image,
            version_url=entry.version_url,
            release_notes_url=entry.release_notes,
            manifest_bucket=entry.manifest_bucket,
        )

    raise BuildNotFoundError(f"Could not resolve {normalized}. " + "; ".join(errors))
