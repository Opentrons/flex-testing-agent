"""Shared compliance App scenario helpers."""

from __future__ import annotations

from flex_testing_agent.app_cdp.pages.login_modal import LoginOutcome
from flex_testing_agent.app_cdp.screenplay.actor import Actor
from flex_testing_agent.app_cdp.screenplay.tasks import LoginAsAdmin, OpenRobot
from flex_testing_agent.fixtures.crs_users import AdminLoginCandidate


class PasswordExpiredError(RuntimeError):
    """Forced password reset could not be completed in the desktop app."""


def login_with_admin_candidates(
    actor: Actor,
    robot_name: str,
    candidates: list[AdminLoginCandidate],
) -> tuple[LoginAsAdmin, list[str]]:
    """Navigate to the robot and log in with the first working admin."""
    actor.attempts_to(OpenRobot(robot_name))
    locked: list[str] = []

    for candidate in candidates:
        login_task = LoginAsAdmin(
            candidate.username,
            candidate.primary_password,
            candidate.alternate_password,
        )
        actor.attempts_to(login_task)
        result = login_task.result
        if result is None:
            msg = "Login task did not record a result"
            raise RuntimeError(msg)

        if result.outcome is LoginOutcome.ACCOUNT_LOCKED:
            locked.append(candidate.username)
            continue

        if result.outcome is LoginOutcome.PASSWORD_EXPIRED:
            raise PasswordExpiredError(
                f"Password expired for {candidate.username} and reset did not "
                "complete. Check CRS_FIXTURE_PASSWORD_ALT or CRS_NEW_PASSWORD."
            )

        if result.outcome is LoginOutcome.INCORRECT_CREDENTIALS:
            detail = result.detail or "incorrect credentials"
            msg = (
                f"Login failed for {candidate.username} after both lab passwords: "
                f"{detail}."
            )
            raise RuntimeError(msg)

        if result.outcome is LoginOutcome.LOGGED_IN:
            return login_task, locked

        detail = result.detail or result.outcome.value
        msg = f"Admin login failed for {candidate.username}: {detail}"
        raise RuntimeError(msg)

    locked_list = ", ".join(locked) if locked else "(none tried successfully)"
    msg = (
        f"No unlocked admin could log in. Locked or rejected: {locked_list}. "
        "Unlock an account via API or provision another admin."
    )
    raise RuntimeError(msg)
