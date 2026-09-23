"""Screenplay tasks for CRS desktop app flows."""

from __future__ import annotations

import os

from flex_testing_agent.app_cdp.pages.login_modal import LoginResult
from flex_testing_agent.app_cdp.screenplay.actor import Actor, Task


class OpenRobot(Task):
    """Navigate to a robot device overview."""

    def __init__(self, robot_name: str) -> None:
        self.robot_name = robot_name

    def perform(self, actor: Actor) -> None:
        actor.robot.open(self.robot_name)


class LoginAsAdmin(Task):
    """Open login modal, submit admin credentials, and handle forced resets."""

    def __init__(
        self,
        username: str,
        primary_password: str,
        alternate_password: str,
    ) -> None:
        self.username = username
        self.primary_password = primary_password
        self.alternate_password = alternate_password
        self.result: LoginResult | None = None
        self.password_expired_detected = False
        self.password_reset_performed = False

    def perform(self, actor: Actor) -> None:
        modal = actor.robot.open_login_modal()
        reset_override = os.environ.get("CRS_NEW_PASSWORD", "").strip() or None
        self.result = modal.authenticate_with_password_pair(
            self.username,
            self.primary_password,
            self.alternate_password,
            reset_override=reset_override,
        )
        self.password_reset_performed = self.result.password_reset_performed
        self.password_expired_detected = self.password_reset_performed


class OpenComplianceUsers(Task):
    """Open Compliance Ready settings and expand User management."""

    def __init__(self, robot_name: str) -> None:
        self.robot_name = robot_name
        self.usernames: list[str] = []

    def perform(self, actor: Actor) -> None:
        actor.compliance.open(self.robot_name)
        self.usernames = actor.compliance.usernames_visible()
