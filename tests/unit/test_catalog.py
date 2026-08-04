"""Tests for the Flex HTTP endpoint catalog (CRS matrix)."""

from __future__ import annotations

import pytest

from flex_testing_agent.catalog import (
    FLEX_HTTP_ENDPOINTS,
    HttpMethod,
    endpoint_count_by_method,
    endpoints_for_crs_off_get_probe,
)
from flex_testing_agent.clients.readonly import READONLY_ENDPOINTS
from flex_testing_agent.models.risk import RiskLevel


@pytest.mark.unit
def test_catalog_has_substantial_surface() -> None:
    assert len(FLEX_HTTP_ENDPOINTS) >= 150
    counts = endpoint_count_by_method()
    assert counts.get("GET", 0) >= 50
    assert counts.get("POST", 0) >= 40


@pytest.mark.unit
def test_crs_enable_is_blocked() -> None:
    blocked = [ep for ep in FLEX_HTTP_ENDPOINTS if ep.blocked]
    assert len(blocked) == 1
    assert blocked[0].method == HttpMethod.PATCH
    assert blocked[0].path == "/auth/settings/accessControlEnabled"


@pytest.mark.unit
def test_physical_motion_is_narrow() -> None:
    motion = {
        ep.path
        for ep in FLEX_HTTP_ENDPOINTS
        if ep.risk_level == RiskLevel.PHYSICAL_MOTION
    }
    assert "/robot/home" in motion
    assert "/robot/move" in motion
    assert "/robot/lights" not in motion


@pytest.mark.unit
def test_crs_off_get_probe_excludes_parameterized_and_redoc() -> None:
    probe = endpoints_for_crs_off_get_probe()
    assert all(ep.method == HttpMethod.GET for ep in probe)
    assert all(not ep.parameterized for ep in probe)
    assert all("redoc" not in ep.path for ep in probe)
    paths = {ep.path for ep in probe}
    assert "/health" in paths
    assert "/auth/settings/accessControlEnabled" in paths
    assert "/accessControl/settings" in paths


@pytest.mark.unit
def test_readonly_endpoints_cover_crs_off_gets() -> None:
    catalog_paths = {ep.path for ep in endpoints_for_crs_off_get_probe()}
    readonly_paths = {ep.path for ep in READONLY_ENDPOINTS}
    assert catalog_paths.issubset(readonly_paths)
    # Concrete camera settings path used by probe summaries.
    assert "/camera/cameraSettings/ot_system_camera" in readonly_paths
    names = {ep.name for ep in READONLY_ENDPOINTS}
    assert "health" in names
    assert "access_control_enabled" in names
    assert "update_health" in names
