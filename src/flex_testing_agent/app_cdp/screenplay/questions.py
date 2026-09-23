"""Screenplay questions (read-only checks)."""

from __future__ import annotations

from flex_testing_agent.app_cdp.screenplay.actor import Actor, Question


class PasswordExpired(Question):
    """True when the login modal shows the forced password-reset step."""

    @classmethod
    def answered_by(cls, actor: Actor) -> bool:
        return actor.login.detect_password_expired()


class AllExpectedUsersVisible(Question):
    """True when every crs_users.yaml fixture user appears in User management."""

    @classmethod
    def answered_by(cls, actor: Actor) -> bool:
        from flex_testing_agent.app_cdp.scenarios.compliance_users import (
            validate_compliance_users,
        )

        visible = actor.compliance.usernames_visible()
        return validate_compliance_users(visible).ok


class UserVisible(Question):
    """True when *username* appears in the User management table."""

    def __init__(self, username: str) -> None:
        self.username = username

    @classmethod
    def for_user(cls, username: str) -> UserVisible:
        return cls(username)

    def check(self, actor: Actor) -> bool:
        return actor.compliance.expects_username(self.username)
