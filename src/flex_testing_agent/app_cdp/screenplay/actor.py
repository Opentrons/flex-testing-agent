"""Screenplay actor: holds the Playwright page and page objects."""

from __future__ import annotations

from dataclasses import dataclass, field

from playwright.sync_api import Page

from flex_testing_agent.app_cdp.pages.compliance_settings import ComplianceSettingsPage
from flex_testing_agent.app_cdp.pages.login_modal import LoginModalPage
from flex_testing_agent.app_cdp.pages.robot_device import RobotDevicePage


@dataclass
class Actor:
    """Test persona with access to page objects."""

    page: Page
    name: str = "Admin"
    robot: RobotDevicePage = field(init=False)
    login: LoginModalPage = field(init=False)
    compliance: ComplianceSettingsPage = field(init=False)

    def __post_init__(self) -> None:
        self.robot = RobotDevicePage(self.page)
        self.login = LoginModalPage(self.page)
        self.compliance = ComplianceSettingsPage(self.page)

    def attempts_to(self, task: Task) -> Task:
        task.perform(self)
        return task


class Task:
    """Base Screenplay task."""

    def perform(self, actor: Actor) -> None:
        raise NotImplementedError


class Question:
    """Base Screenplay question."""

    @classmethod
    def answered_by(cls, actor: Actor) -> bool:
        raise NotImplementedError
