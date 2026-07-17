"""Unit tests for domain models."""

from __future__ import annotations

import pytest

from flex_testing_agent.models.access_control import (
    AccessControlState,
    AccessControlStatus,
)
from flex_testing_agent.models.health import HealthReport, UpdateHealthReport
from flex_testing_agent.models.snapshot import RobotSnapshot


@pytest.mark.unit
def test_health_report_from_robot_server_shape(
    sample_health_payload: dict[str, object],
) -> None:
    report = HealthReport.model_validate(sample_health_payload)
    assert report.name == "Kansas"
    assert report.api_version == "8.5.0"
    assert report.disk_details is not None
    assert report.disk_details.system_available_mb == 10000.0
    assert report.is_healthy is True


@pytest.mark.unit
def test_update_health_aliases(
    sample_update_health_payload: dict[str, object],
) -> None:
    report = UpdateHealthReport.model_validate(sample_update_health_payload)
    assert report.update_server_version == "8.5.0"
    assert report.system_version == "2026.1.0"


@pytest.mark.unit
def test_snapshot_derived_fields(
    sample_health_payload: dict[str, object],
    sample_update_health_payload: dict[str, object],
) -> None:
    snapshot = RobotSnapshot(
        configured_name="Kansas",
        host="127.0.0.1",
        base_url="http://127.0.0.1:31950",
        connectivity=True,
        health=HealthReport.model_validate(sample_health_payload),
        update_health=UpdateHealthReport.model_validate(sample_update_health_payload),
        access_control=AccessControlStatus(
            state=AccessControlState.DISABLED,
            raw_enabled=False,
        ),
    )
    assert snapshot.robot_display_name == "Kansas"
    assert snapshot.installed_software_version == "2026.1.0"
    assert snapshot.api_version == "8.5.0"
