"""Live desktop app scenario: compliance settings UI vs API."""

from __future__ import annotations

import pytest

from flex_testing_agent.app_cdp.connect import launch_and_attach
from flex_testing_agent.app_cdp.scenarios.compliance_common import PasswordExpiredError
from flex_testing_agent.app_cdp.scenarios.compliance_settings import (
    run_compliance_settings_scenario,
)
from flex_testing_agent.config.settings import get_settings


@pytest.mark.requires_robot
def test_app_compliance_settings_match_api() -> None:
    """Requires KansasFLEX reachable, CRS on, and the Opentrons desktop app."""
    settings = get_settings()
    connection = launch_and_attach(quiet=True)
    try:
        try:
            result = run_compliance_settings_scenario(
                connection.page,
                settings=settings,
            )
        except PasswordExpiredError as exc:
            pytest.fail(f"Password reset flow failed: {exc}")
    finally:
        connection.close()

    assert result.login_outcome.value == "logged_in"
    assert result.validation.ok is True
