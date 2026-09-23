"""Live desktop app scenario: admin login and compliance users."""

from __future__ import annotations

import pytest

from flex_testing_agent.app_cdp.connect import launch_and_attach
from flex_testing_agent.app_cdp.scenarios.compliance_common import PasswordExpiredError
from flex_testing_agent.app_cdp.scenarios.compliance_users import (
    run_compliance_users_scenario,
)
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.fixtures.crs_users import expected_compliance_ui_usernames


@pytest.mark.requires_robot
def test_app_compliance_users_admin_login() -> None:
    """Requires KansasFLEX reachable and the Opentrons desktop app."""
    settings = get_settings()
    connection = launch_and_attach(quiet=True)
    try:
        try:
            result = run_compliance_users_scenario(connection.page, settings=settings)
        except PasswordExpiredError as exc:
            pytest.fail(f"Password reset flow failed: {exc}")
    finally:
        connection.close()

    assert result.login_outcome.value == "logged_in"
    assert result.validation.ok is True
    for username in expected_compliance_ui_usernames():
        assert username in result.usernames
