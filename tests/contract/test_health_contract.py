"""Contract checks derived from inspected robot-server health schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from flex_testing_agent.models.health import HealthReport

REQUIRED_HEALTH_FIELDS = {
    "name",
    "robot_model",
    "api_version",
    "fw_version",
    "board_revision",
    "system_version",
}


@pytest.mark.contract
def test_health_requires_core_fields(
    sample_health_payload: dict[str, object],
) -> None:
    for field in REQUIRED_HEALTH_FIELDS:
        payload = dict(sample_health_payload)
        del payload[field]
        with pytest.raises(ValidationError):
            HealthReport.model_validate(payload)


@pytest.mark.contract
def test_health_accepts_known_robot_server_shape(
    sample_health_payload: dict[str, object],
) -> None:
    report = HealthReport.model_validate(sample_health_payload)
    assert report.robot_model == "OT-3 Standard"
