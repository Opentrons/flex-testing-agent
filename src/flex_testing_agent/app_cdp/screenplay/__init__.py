"""Screenplay pattern primitives for desktop app automation."""

from flex_testing_agent.app_cdp.screenplay.actor import Actor
from flex_testing_agent.app_cdp.screenplay.questions import (
    AllExpectedUsersVisible,
    PasswordExpired,
    UserVisible,
)
from flex_testing_agent.app_cdp.screenplay.tasks import (
    LoginAsAdmin,
    OpenComplianceUsers,
    OpenRobot,
)

__all__ = [
    "Actor",
    "AllExpectedUsersVisible",
    "LoginAsAdmin",
    "OpenComplianceUsers",
    "OpenRobot",
    "PasswordExpired",
    "UserVisible",
]
