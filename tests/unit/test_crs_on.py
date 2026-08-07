"""Unit tests for CRS-on fixtures and settings."""

from __future__ import annotations

from pathlib import Path

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.crs_users import (
    load_crs_user_fixtures,
    resolve_fixture_password,
)


def test_load_bundled_crs_user_fixtures() -> None:
    fixture_file = load_crs_user_fixtures()
    assert fixture_file.version == 1
    bootstrap = fixture_file.require_bootstrap_admin()
    assert bootstrap.username == "flex_harness_admin"
    enabled = fixture_file.enabled_users()
    usernames = {user.username for user in enabled}
    assert "flex_test_admin" in usernames
    assert "flex_test_operator" in usernames
    assert "testadmin" not in usernames


def test_resolve_fixture_password_lab_default() -> None:
    fixture_file = load_crs_user_fixtures()
    admin = next(
        user for user in fixture_file.users if user.username == "flex_test_admin"
    )
    assert (
        resolve_fixture_password(admin, defaults=fixture_file.defaults)
        == "FlexHarnessUsers1!"
    )


def test_resolve_fixture_password_env(monkeypatch) -> None:
    fixture_file = load_crs_user_fixtures()
    admin = next(
        user for user in fixture_file.users if user.username == "flex_test_admin"
    )
    monkeypatch.setenv("CRS_PASSWORD_FLEX_TEST_ADMIN", "secret-admin")
    assert (
        resolve_fixture_password(admin, defaults=fixture_file.defaults)
        == "secret-admin"
    )


def test_robot_certs_directory_default(tmp_path: Path) -> None:
    settings = Settings(robot_host="192.168.0.21", artifact_directory=tmp_path)
    assert settings.robot_certs_directory == tmp_path / "robot-certs"
