"""Page objects for the Opentrons desktop app."""

from flex_testing_agent.app_cdp.pages.compliance_settings import ComplianceSettingsPage
from flex_testing_agent.app_cdp.pages.login_modal import LoginModalPage, LoginOutcome
from flex_testing_agent.app_cdp.pages.robot_device import RobotDevicePage

__all__ = [
    "ComplianceSettingsPage",
    "LoginModalPage",
    "LoginOutcome",
    "RobotDevicePage",
]
