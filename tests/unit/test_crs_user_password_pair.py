"""Unit tests for CRS fixture password pairs and reset toggling."""

from __future__ import annotations

import pytest

from flex_testing_agent.fixtures.crs_users import (
    admin_login_candidates,
    default_crs_user_fixtures,
    fixture_password_for_reset,
    resolve_fixture_password_alt,
    resolve_user_password_pair,
)


def test_resolve_user_password_pair_defaults() -> None:
    primary, alternate = resolve_user_password_pair("flex_test_admin")
    assert primary == "FlexHarnessUsers1!"
    assert alternate == "FlexHarnessUsers2!"


def test_resolve_user_password_pair_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRS_FIXTURE_PASSWORD", "Primary1!")
    monkeypatch.setenv("CRS_FIXTURE_PASSWORD_ALT", "Alternate1!")

    primary, alternate = resolve_user_password_pair("flex_test_admin")
    assert primary == "Primary1!"
    assert alternate == "Alternate1!"


def test_fixture_password_for_reset_toggles() -> None:
    primary = "FlexHarnessUsers1!"
    alternate = "FlexHarnessUsers2!"
    assert (
        fixture_password_for_reset(
            primary,
            primary_password=primary,
            alternate_password=alternate,
        )
        == alternate
    )
    assert (
        fixture_password_for_reset(
            alternate,
            primary_password=primary,
            alternate_password=alternate,
        )
        == primary
    )


def test_resolve_fixture_password_alt_requires_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures = default_crs_user_fixtures()
    defaults = {**fixtures.defaults, "lab_password_alt": ""}
    monkeypatch.delenv("CRS_FIXTURE_PASSWORD_ALT", raising=False)

    with pytest.raises(ValueError, match="lab_password_alt"):
        resolve_fixture_password_alt(None, defaults=defaults)


def test_admin_login_candidates_includes_bootstrap_after_fixture_admins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CRS_APP_ADMIN_USERNAME", raising=False)
    candidates = admin_login_candidates()
    usernames = [candidate.username for candidate in candidates]
    assert usernames.index("flex_test_admin") < usernames.index("flex_harness_admin")
    assert "flex_backup_admin" not in usernames


def test_resolve_backup_admin_inline_password() -> None:
    primary, alternate = resolve_user_password_pair("flex_backup_admin")
    assert primary == "FlexBackupAdmin1!"
    assert alternate == "FlexHarnessUsers2!"


def test_resolve_bootstrap_admin_password_pair_defaults() -> None:
    primary, alternate = resolve_user_password_pair("flex_harness_admin")
    assert primary == "FlexHarnessAdmin1!"
    assert alternate == "FlexHarnessAdmin2!"


def test_resolve_bootstrap_admin_password_pair_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRS_ADMIN_PASSWORD", "BootstrapPrimary1!")
    monkeypatch.setenv("CRS_ADMIN_PASSWORD_ALT", "BootstrapAlternate1!")

    primary, alternate = resolve_user_password_pair("flex_harness_admin")
    assert primary == "BootstrapPrimary1!"
    assert alternate == "BootstrapAlternate1!"
