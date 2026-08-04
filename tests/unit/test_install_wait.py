"""Unit tests for post-install reboot wait (update-server vs /health)."""

from __future__ import annotations

import httpx
import pytest
import respx

from flex_testing_agent.capabilities.install import _wait_for_reboot_and_version
from flex_testing_agent.config.settings import Settings


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_wait_accepts_update_health_when_health_stays_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OS version from update-server should finish boot even if /health is 500."""
    monkeypatch.setattr(
        "flex_testing_agent.capabilities.install.asyncio.sleep",
        _instant_sleep,
    )
    settings = Settings(
        robot_host="127.0.0.1",
        robot_health_timeout_seconds=1.0,
        robot_request_timeout_seconds=1.0,
    )
    respx.get("http://127.0.0.1:31950/server/update/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "updateServerVersion": "4.0.0-alpha.10",
                "apiServerVersion": "4.0.0-alpha.10",
                "systemVersion": "ot3@4.0.0-alpha.10",
                "capabilities": {},
            },
        )
    )
    respx.get("http://127.0.0.1:31950/health").mock(
        return_value=httpx.Response(
            500,
            json={
                "errors": [
                    {
                        "id": "DatabaseFailedToInitialize",
                        "detail": "Device or resource busy",
                    }
                ]
            },
        )
    )

    # Force a short deadline by patching the loop clock after first iteration.
    result = await _wait_for_reboot_and_version(
        settings,
        expected_version="4.0.0-alpha.10",
        timeout_seconds=0.05,
        poll_interval_seconds=0.01,
    )
    assert result["source"] == "update_health"
    assert result["robot_server_healthy"] is False
    assert "4.0.0-alpha.10" in str(result["system_version"])


async def _instant_sleep(_seconds: float) -> None:
    return None
