"""Flex release catalog discovery (robot-stack aligned)."""

from flex_testing_agent.releases.catalog import FlexReleaseCatalog, summarize_latest
from flex_testing_agent.releases.client import fetch_flex_release_summary
from flex_testing_agent.releases.urls import ReleaseChannel
from flex_testing_agent.releases.versions import ReleaseStability

__all__ = [
    "FlexReleaseCatalog",
    "ReleaseChannel",
    "ReleaseStability",
    "fetch_flex_release_summary",
    "summarize_latest",
]
