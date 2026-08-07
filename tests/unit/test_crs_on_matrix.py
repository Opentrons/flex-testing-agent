"""Unit tests for CRS-on auth matrix helpers."""

from __future__ import annotations

from flex_testing_agent.catalog.crs_on_matrix import (
    account_has_required_scopes,
    endpoints_for_crs_on_auth_matrix,
)


def test_account_has_required_scopes() -> None:
    assert account_has_required_scopes("auditor", ("users.read.others",))
    assert not account_has_required_scopes(
        "user",
        ("users.read.others",),
    )
    assert account_has_required_scopes(
        "user",
        ("robot_control.write",),
    )
    assert account_has_required_scopes(
        "user",
        ("users.read.self",),
    )
    assert not account_has_required_scopes(
        "user",
        ("users.write", "users.read.self"),
    )


def test_endpoints_for_crs_on_auth_matrix_includes_auth_users() -> None:
    names = {ep.name for ep in endpoints_for_crs_on_auth_matrix()}
    assert "get_auth_users_self" in names
    assert "get_auth_users_byUsername_username" in names


def test_get_auth_users_self_scope_matches_auth_server() -> None:
    by_name = {ep.name: ep for ep in endpoints_for_crs_on_auth_matrix()}
    self_ep = by_name["get_auth_users_self"]
    assert self_ep.required_scopes == ("users.read.self",)
