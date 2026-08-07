"""Unit tests for CRS-on probe helpers."""

from __future__ import annotations

from flex_testing_agent.fixtures.crs_users import (
    load_crs_user_fixtures,
    resolve_user_password,
)


def test_resolve_user_password_bootstrap_and_fixture() -> None:
    fixtures = load_crs_user_fixtures()
    assert (
        resolve_user_password("flex_harness_admin", fixture_file=fixtures)
        == "FlexHarnessAdmin1!"
    )
    assert (
        resolve_user_password("flex_test_operator", fixture_file=fixtures)
        == "FlexHarnessUsers1!"
    )
    assert resolve_user_password("missing_user", fixture_file=fixtures) is None
