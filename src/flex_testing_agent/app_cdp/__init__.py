"""Attach to the Opentrons desktop app over Chrome DevTools Protocol (CDP)."""

from flex_testing_agent.app_cdp.connect import (
    AppCdpConnection,
    attach_to_app,
    cdp_is_ready,
    launch_and_attach,
    resolve_cdp_endpoint,
)
from flex_testing_agent.app_cdp.discovery import get_opentrons_app_path
from flex_testing_agent.app_cdp.pages.login_modal import LoginModalPage, LoginOutcome
from flex_testing_agent.app_cdp.scenarios.compliance_common import PasswordExpiredError
from flex_testing_agent.app_cdp.scenarios.compliance_settings import (
    run_compliance_settings_scenario,
)
from flex_testing_agent.app_cdp.scenarios.compliance_users import (
    run_compliance_users_scenario,
)

__all__ = [
    "AppCdpConnection",
    "LoginModalPage",
    "LoginOutcome",
    "PasswordExpiredError",
    "attach_to_app",
    "cdp_is_ready",
    "get_opentrons_app_path",
    "launch_and_attach",
    "resolve_cdp_endpoint",
    "run_compliance_settings_scenario",
    "run_compliance_users_scenario",
]
