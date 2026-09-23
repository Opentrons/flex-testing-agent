"""Fetch CRS settings over HTTPS for App UI cross-check scenarios."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.auth_settings import AuthSettingsData
from flex_testing_agent.orchestration.discover import settings_with_resolved_host
from flex_testing_agent.robots.flex import build_robot_http_session


async def fetch_settings_snapshots(
    settings: Settings,
    admin_username: str,
) -> tuple[AuthSettingsData, dict[str, Any]]:
    """Return auth settings and audit external settings from the robot API."""
    resolved = await settings_with_resolved_host(settings)
    token = await access_token_for_username(resolved, admin_username)
    async with build_robot_http_session(resolved, access_token=token) as session:
        auth_payload = await session.get_json("/auth/settings")
        audit_payload = await session.get_json("/audit/external/settings")
    auth = AuthSettingsData.model_validate(auth_payload["data"])
    audit_data = dict(audit_payload.get("data") or {})
    return auth, audit_data


def fetch_settings_snapshots_sync(
    settings: Settings,
    admin_username: str,
) -> tuple[AuthSettingsData, dict[str, Any]]:
    """Sync wrapper safe under Playwright's running event loop."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            asyncio.run,
            fetch_settings_snapshots(settings, admin_username),
        )
        return future.result()
