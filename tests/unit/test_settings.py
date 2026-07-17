"""Unit tests for configuration."""

from __future__ import annotations

import pytest

from flex_testing_agent.config.settings import Settings, clear_settings_cache


@pytest.mark.unit
def test_robot_base_url_http() -> None:
    settings = Settings(
        robot_host="10.0.0.5",
        robot_use_https=False,
        robot_http_port=31950,
    )
    assert settings.robot_base_url == "http://10.0.0.5:31950"


@pytest.mark.unit
def test_robot_base_url_https() -> None:
    settings = Settings(
        robot_host="10.0.0.5",
        robot_use_https=True,
        robot_https_port=32313,
    )
    assert settings.robot_base_url == "https://10.0.0.5:32313"


@pytest.mark.unit
def test_require_robot_host_raises_when_empty() -> None:
    settings = Settings(robot_host="")
    with pytest.raises(ValueError, match="ROBOT_HOST"):
        settings.require_robot_host()


@pytest.mark.unit
def test_mutations_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.delenv("ALLOW_MUTATIONS", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    # Bypass .env so the test asserts code defaults, not a local lab .env.
    settings = Settings(_env_file=None)
    assert settings.allow_mutations is False
    assert settings.dry_run is False
