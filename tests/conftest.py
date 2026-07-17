"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from flex_testing_agent.config.settings import Settings, clear_settings_cache


@pytest.fixture
def tmp_artifacts(tmp_path: Path) -> Path:
    """Temporary artifact directory."""
    path = tmp_path / "artifacts"
    path.mkdir()
    return path


@pytest.fixture
def settings(tmp_artifacts: Path, tmp_path: Path) -> Settings:
    """Settings pointed at ephemeral paths and a fake robot host."""
    clear_settings_cache()
    db_path = tmp_path / "test.db"
    return Settings(
        robot_host="127.0.0.1",
        robot_name="KansasFLEX",
        robot_http_port=31950,
        robot_use_https=False,
        robot_request_timeout_seconds=5.0,
        robot_health_timeout_seconds=5.0,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        artifact_directory=tmp_artifacts,
        allow_mutations=False,
        dry_run=False,
        log_level="WARNING",
    )


@pytest.fixture
def sample_health_payload() -> dict[str, object]:
    """Minimal valid /health payload shaped like robot-server Health."""
    return {
        "name": "Kansas",
        "robot_model": "OT-3 Standard",
        "api_version": "8.5.0",
        "fw_version": "v1.0.0",
        "board_revision": "1.0",
        "logs": ["/logs/api.log"],
        "system_version": "2026.1.0",
        "maximum_protocol_api_version": [2, 24],
        "minimum_protocol_api_version": [2, 0],
        "robot_serial": "FLX000TEST",
        "disk_details": {
            "systemAvailableMb": 10000.0,
            "systemTotalMb": 20000.0,
            "imagesDirectorySizeMb": 100.0,
        },
        "links": {
            "apiLog": "/logs/api.log",
            "serialLog": "/logs/serial.log",
            "serverLog": "/logs/server.log",
            "apiSpec": "/openapi.json",
            "systemTime": "/system/time",
        },
    }


@pytest.fixture
def sample_update_health_payload() -> dict[str, object]:
    """Minimal valid /server/update/health payload."""
    return {
        "updateServerVersion": "8.5.0",
        "apiServerVersion": "8.5.0",
        "systemVersion": "2026.1.0",
        "robotModel": "OT-3 Standard",
        "capabilities": {"bootstrap": "/server/update/begin"},
    }
