"""HTTP client for Flex robot OS release manifests."""

from __future__ import annotations

from typing import Any

import httpx

from flex_testing_agent.releases.catalog import (
    FlexReleaseCatalog,
    FlexReleaseSummary,
    build_catalog,
)
from flex_testing_agent.releases.urls import ReleaseChannel, robot_releases_json_url


async def fetch_robot_manifest(
    channel: ReleaseChannel,
    *,
    timeout_seconds: float = 15.0,
    client: httpx.AsyncClient | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch ``ot3-oe/releases.json`` for a channel.

    Returns:
        ``(manifest, error)``. On success error is None.
    """
    url = robot_releases_json_url(channel)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout_seconds)
    try:
        response = await http.get(url)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return None, f"Expected JSON object from {url}"
        return data, None
    except Exception as exc:
        return None, f"{url}: {exc}"
    finally:
        if owns_client:
            await http.aclose()


async def fetch_channel_catalog(
    channel: ReleaseChannel,
    *,
    timeout_seconds: float = 15.0,
    client: httpx.AsyncClient | None = None,
) -> FlexReleaseCatalog:
    """Fetch and parse one channel catalog."""
    url = robot_releases_json_url(channel)
    manifest, error = await fetch_robot_manifest(
        channel, timeout_seconds=timeout_seconds, client=client
    )
    if error or manifest is None:
        return FlexReleaseCatalog(
            channel=channel,
            manifest_url=url,
            error=error or "unknown fetch error",
        )
    return build_catalog(channel=channel, manifest_url=url, manifest=manifest)


async def fetch_flex_release_summary(
    *,
    timeout_seconds: float = 15.0,
) -> FlexReleaseSummary:
    """Fetch latest internal and external Flex robot OS release catalogs."""
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        internal = await fetch_channel_catalog(
            ReleaseChannel.INTERNAL,
            timeout_seconds=timeout_seconds,
            client=client,
        )
        external = await fetch_channel_catalog(
            ReleaseChannel.EXTERNAL,
            timeout_seconds=timeout_seconds,
            client=client,
        )
    return FlexReleaseSummary(internal=internal, external=external)
