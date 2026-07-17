"""Unit tests for Flex release catalog parsing and version helpers."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.releases.catalog import build_catalog, summarize_latest
from flex_testing_agent.releases.client import fetch_flex_release_summary
from flex_testing_agent.releases.urls import ReleaseChannel, robot_releases_json_url
from flex_testing_agent.releases.versions import (
    ReleaseStability,
    classify_stability,
    normalize_robot_version,
    stack_tag_for_version,
)


@pytest.mark.unit
def test_normalize_robot_version_variants() -> None:
    assert normalize_robot_version("4.0.0-alpha.5") == "4.0.0-alpha.5"
    assert normalize_robot_version("ot3@4.0.0-alpha.5") == "4.0.0-alpha.5"
    assert normalize_robot_version("v9.1.0-beta.0") == "9.1.0-beta.0"
    assert normalize_robot_version("v9.1.0") == "9.1.0"
    assert normalize_robot_version("not-a-version") is None


@pytest.mark.unit
def test_classify_and_stack_tags() -> None:
    assert classify_stability("4.0.0") == ReleaseStability.STABLE
    assert classify_stability("ot3@4.0.0-alpha.5") == ReleaseStability.ALPHA
    assert classify_stability("v9.1.0-beta.0") == ReleaseStability.BETA
    assert (
        stack_tag_for_version("4.0.0-alpha.5", ReleaseChannel.INTERNAL)
        == "ot3@4.0.0-alpha.5"
    )
    assert (
        stack_tag_for_version("9.1.0-beta.0", ReleaseChannel.EXTERNAL)
        == "v9.1.0-beta.0"
    )


@pytest.mark.unit
def test_merge_production_v2_and_latest_lanes() -> None:
    manifest = {
        "production": {
            "9.1.0": {
                "fullImage": "https://example/old/full.tar",
                "system": "https://example/old/system.zip",
                "version": "https://example/old/VERSION.json",
                "releaseNotes": "https://example/old/notes.md",
            },
            "9.1.0-alpha.0": {
                "fullImage": "https://example/a0/full.tar",
                "system": "https://example/a0/system.zip",
                "version": "https://example/a0/VERSION.json",
                "releaseNotes": "https://example/a0/notes.md",
            },
        },
        "productionV2": {
            "9.1.0-alpha.2": {
                "fullImage": "https://example/a2/full.tar",
                "system": "https://example/a2/system.zip",
                "version": "https://example/a2/VERSION.json",
                "releaseNotes": "https://example/a2/notes.md",
            },
            "9.1.0-beta.1": {
                "fullImage": "https://example/b1/full.tar",
                "system": "https://example/b1/system.zip",
                "version": "https://example/b1/VERSION.json",
                "releaseNotes": "https://example/b1/notes.md",
            },
        },
    }
    catalog = build_catalog(
        channel=ReleaseChannel.EXTERNAL,
        manifest_url=robot_releases_json_url(ReleaseChannel.EXTERNAL),
        manifest=manifest,
    )
    assert catalog.latest.stable is not None
    assert catalog.latest.stable.version == "9.1.0"
    assert catalog.latest.alpha is not None
    assert catalog.latest.alpha.version == "9.1.0-alpha.2"
    assert catalog.latest.beta is not None
    assert catalog.latest.beta.version == "9.1.0-beta.1"
    assert catalog.latest.alpha.stack_tag == "v9.1.0-alpha.2"
    assert catalog.latest.alpha.manifest_bucket == "productionV2"


@pytest.mark.unit
def test_summarize_latest_prefers_higher_semver() -> None:
    catalog = build_catalog(
        channel=ReleaseChannel.INTERNAL,
        manifest_url="https://example/releases.json",
        manifest={
            "productionV2": {
                "4.0.0-beta.0": {
                    "fullImage": "a",
                    "system": "b",
                    "version": "c",
                    "releaseNotes": "d",
                },
                "4.0.0-beta.1": {
                    "fullImage": "a",
                    "system": "b",
                    "version": "c",
                    "releaseNotes": "d",
                },
                "3.1.0-alpha.9": {
                    "fullImage": "a",
                    "system": "b",
                    "version": "c",
                    "releaseNotes": "d",
                },
                "4.0.0-alpha.5": {
                    "fullImage": "a",
                    "system": "b",
                    "version": "c",
                    "releaseNotes": "d",
                },
            }
        },
    )
    latest = summarize_latest(catalog.entries)
    assert latest.beta is not None and latest.beta.version == "4.0.0-beta.1"
    assert latest.alpha is not None and latest.alpha.version == "4.0.0-alpha.5"
    assert latest.stable is None


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_fetch_flex_release_summary_both_channels() -> None:
    internal_body = {
        "productionV2": {
            "4.0.0-alpha.5": {
                "fullImage": "https://i/full",
                "system": "https://i/sys",
                "version": "https://i/ver",
                "releaseNotes": "https://i/notes",
            }
        }
    }
    external_body = {
        "production": {
            "8.5.0": {
                "fullImage": "https://e/full",
                "system": "https://e/sys",
                "version": "https://e/ver",
                "releaseNotes": "https://e/notes",
            }
        }
    }
    respx.get(robot_releases_json_url(ReleaseChannel.INTERNAL)).mock(
        return_value=httpx.Response(200, json=internal_body)
    )
    respx.get(robot_releases_json_url(ReleaseChannel.EXTERNAL)).mock(
        return_value=httpx.Response(200, json=external_body)
    )

    summary = await fetch_flex_release_summary(timeout_seconds=5.0)
    assert summary.internal.error is None
    assert summary.external.error is None
    assert summary.internal.latest.alpha is not None
    assert summary.internal.latest.alpha.version == "4.0.0-alpha.5"
    assert summary.internal.latest.alpha.stack_tag == "ot3@4.0.0-alpha.5"
    assert summary.external.latest.stable is not None
    assert summary.external.latest.stable.version == "8.5.0"


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_fetch_records_channel_error() -> None:
    respx.get(robot_releases_json_url(ReleaseChannel.INTERNAL)).mock(
        return_value=httpx.Response(500, text="boom")
    )
    respx.get(robot_releases_json_url(ReleaseChannel.EXTERNAL)).mock(
        return_value=httpx.Response(
            200,
            json={
                "production": {
                    "8.5.0": {
                        "fullImage": "a",
                        "system": "b",
                        "version": "c",
                        "releaseNotes": "d",
                    }
                }
            },
        )
    )
    summary = await fetch_flex_release_summary(timeout_seconds=5.0)
    assert summary.internal.error is not None
    assert summary.external.error is None
