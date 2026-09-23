"""Login modal page object (Compliance Ready Software Login)."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from flex_testing_agent.app_cdp.base import click_portal_confirm, hash_path, portal
from flex_testing_agent.app_cdp.pages.documentation_modal import DocumentationModalPage
from flex_testing_agent.fixtures.crs_users import fixture_password_for_reset

PASSWORD_EXPIRED_HEADING = "Your password has expired"
PASSWORD_EXPIRED_SUBHEADING = "Create a new password to use"
ACCOUNT_LOCKED_SNIPPET = "Account locked"
INCORRECT_CREDENTIALS_SNIPPET = "Incorrect username or password"
ATTEMPTS_REMAINING_SNIPPET = "attempts remaining before lockout"
LOGIN_MODAL_HEADER = "Compliance Ready Software Login"


def is_incorrect_credentials(detail: str | None) -> bool:
    """Return True for invalid username/password errors (retry alternate password)."""
    return detail is not None and INCORRECT_CREDENTIALS_SNIPPET in detail


def is_lockout_warning(detail: str | None) -> bool:
    """Return True when the UI warns how many attempts remain before lockout."""
    return detail is not None and ATTEMPTS_REMAINING_SNIPPET in detail


class LoginOutcome(enum.StrEnum):
    """Result of submitting credentials in the desktop login modal."""

    LOGGED_IN = "logged_in"
    PASSWORD_EXPIRED = "password_expired"
    ACCOUNT_LOCKED = "account_locked"
    INCORRECT_CREDENTIALS = "incorrect_credentials"
    LOGIN_FAILED = "login_failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class LoginResult:
    """Structured login attempt result."""

    outcome: LoginOutcome
    detail: str | None = None
    password_used: str | None = None
    password_reset_performed: bool = False


class LoginModalPage:
    """Compliance Ready Software login modal in the top portal."""

    def __init__(self, page: Page) -> None:
        self._page = page
        self._portal = portal(page)

    @property
    def is_open(self) -> bool:
        if self._portal.locator("input[name='username']").count() > 0:
            return True
        if self._portal.get_by_text(PASSWORD_EXPIRED_HEADING, exact=True).count() > 0:
            return True
        return bool(
            self._portal.get_by_text(LOGIN_MODAL_HEADER, exact=True).count() > 0
        )

    @property
    def password_expired_visible(self) -> bool:
        return self.detect_password_expired()

    def detect_password_expired(self) -> bool:
        """Return True when the app shows the forced password-reset step."""
        if self._portal.get_by_text(PASSWORD_EXPIRED_HEADING, exact=True).count() > 0:
            return True
        if self._portal.locator("input[name='newPassword']").count() > 0:
            return True
        return bool(
            self._portal.get_by_text(PASSWORD_EXPIRED_SUBHEADING, exact=True).count()
            > 0
        )

    def wait_for_password_expired(self, *, timeout_ms: float = 10_000) -> None:
        deadline = time.time() + (timeout_ms / 1000)
        while time.time() < deadline:
            if self.detect_password_expired():
                return
            time.sleep(0.2)
        msg = "Timed out waiting for password-expired view"
        raise PlaywrightTimeoutError(msg)

    def wait_for_login_form(self) -> None:
        """Wait until the login or password-expired step is visible."""
        if self._login_form_visible() or self.detect_password_expired():
            return
        deadline = time.time() + 5
        while time.time() < deadline:
            if self._login_form_visible() or self.detect_password_expired():
                return
            time.sleep(0.2)
        msg = "Login modal did not appear"
        raise PlaywrightTimeoutError(msg)

    def submit_credentials(self, username: str, password: str) -> LoginResult:
        """Fill username/password and submit. Does not wait for modal close."""
        if self._session_active_on_device():
            return LoginResult(outcome=LoginOutcome.LOGGED_IN, password_used=password)
        self.wait_for_login_form()
        if self.detect_password_expired():
            return LoginResult(
                outcome=LoginOutcome.PASSWORD_EXPIRED,
                detail=PASSWORD_EXPIRED_HEADING,
            )
        self._portal.locator("input[name='username']").fill(username)
        self._portal.locator("input[name='password']").fill(password)
        self._portal.get_by_role("button", name="Log in").click()
        return self.wait_for_outcome()

    def complete_password_reset(self, new_password: str) -> LoginResult:
        """Set a new password when ``resetPassword`` forced the expired view."""
        self.wait_for_password_expired()
        self._portal.locator("input[name='newPassword']").fill(new_password)
        self._portal.locator("input[name='confirmPassword']").fill(new_password)
        click_portal_confirm(self._portal, label="Confirm")
        documentation = DocumentationModalPage(self._page)
        if documentation.is_open():
            documentation.confirm()
        return self.wait_for_outcome(after_password_reset=True)

    def authenticate_with_password_pair(
        self,
        username: str,
        primary_password: str,
        alternate_password: str,
        *,
        reset_override: str | None = None,
    ) -> LoginResult:
        """Log in, trying both lab passwords and completing forced resets."""
        reset_performed = False
        last_result = LoginResult(outcome=LoginOutcome.LOGIN_FAILED)

        for password in (primary_password, alternate_password):
            result = self._attempt_login_or_reset(
                username=username,
                password=password,
                primary_password=primary_password,
                alternate_password=alternate_password,
                reset_override=reset_override,
                reset_performed=reset_performed,
            )
            reset_performed = reset_performed or result.password_reset_performed
            last_result = result
            if result.outcome == LoginOutcome.LOGGED_IN:
                return result
            if result.outcome is LoginOutcome.INCORRECT_CREDENTIALS:
                # Wrong lab password: try the alternate before lockout escalates.
                continue
            if result.outcome in {
                LoginOutcome.ACCOUNT_LOCKED,
                LoginOutcome.TIMEOUT,
            }:
                return result

        return last_result

    def _attempt_login_or_reset(
        self,
        *,
        username: str,
        password: str,
        primary_password: str,
        alternate_password: str,
        reset_override: str | None,
        reset_performed: bool,
    ) -> LoginResult:
        result = self.submit_credentials(username, password)
        if result.outcome is LoginOutcome.LOGGED_IN:
            return LoginResult(
                outcome=LoginOutcome.LOGGED_IN,
                password_used=password,
                password_reset_performed=reset_performed,
            )
        if result.outcome is not LoginOutcome.PASSWORD_EXPIRED:
            return LoginResult(
                outcome=result.outcome,
                detail=result.detail,
                password_used=password,
                password_reset_performed=reset_performed,
            )

        reset_to = (reset_override or "").strip() or fixture_password_for_reset(
            password,
            primary_password=primary_password,
            alternate_password=alternate_password,
        )
        reset_result = self.complete_password_reset(reset_to)
        if reset_result.outcome is LoginOutcome.LOGGED_IN:
            return LoginResult(
                outcome=LoginOutcome.LOGGED_IN,
                password_used=reset_to,
                password_reset_performed=True,
            )
        login_after_reset = self.submit_credentials(username, reset_to)
        return LoginResult(
            outcome=login_after_reset.outcome,
            detail=login_after_reset.detail,
            password_used=reset_to,
            password_reset_performed=True,
        )

    def wait_for_outcome(
        self,
        *,
        timeout_ms: float = 15_000,
        after_password_reset: bool = False,
    ) -> LoginResult:
        deadline = time.time() + (timeout_ms / 1000)
        while time.time() < deadline:
            if self.detect_password_expired() and not after_password_reset:
                return LoginResult(
                    outcome=LoginOutcome.PASSWORD_EXPIRED,
                    detail=PASSWORD_EXPIRED_HEADING,
                )

            if self._portal.get_by_text(ACCOUNT_LOCKED_SNIPPET, exact=False).count():
                detail = self._first_visible_text(
                    self._portal.get_by_text(ACCOUNT_LOCKED_SNIPPET, exact=False)
                )
                return LoginResult(
                    outcome=LoginOutcome.ACCOUNT_LOCKED,
                    detail=detail,
                )

            if self._login_form_visible():
                if after_password_reset:
                    return LoginResult(
                        outcome=LoginOutcome.LOGIN_FAILED,
                        detail="Returned to login after password reset",
                    )
                error = self._read_login_error()
                if error is not None:
                    if is_incorrect_credentials(error):
                        return LoginResult(
                            outcome=LoginOutcome.INCORRECT_CREDENTIALS,
                            detail=error,
                        )
                    if ACCOUNT_LOCKED_SNIPPET in error:
                        return LoginResult(
                            outcome=LoginOutcome.ACCOUNT_LOCKED,
                            detail=error,
                        )
                    return LoginResult(
                        outcome=LoginOutcome.LOGIN_FAILED,
                        detail=error,
                    )
            else:
                if self._session_active_on_device():
                    return LoginResult(outcome=LoginOutcome.LOGGED_IN)

            time.sleep(0.25)

        return LoginResult(outcome=LoginOutcome.TIMEOUT)

    def _session_active_on_device(self) -> bool:
        if self._page.get_by_text("Log out", exact=False).count() > 0:
            return True
        if self.is_open:
            return False
        login = self._page.get_by_role("button", name="Log in")
        if login.count() > 0 and login.first.is_visible():
            return False
        return hash_path(self._page).startswith("/devices/")

    def _login_form_visible(self) -> bool:
        return bool(self._portal.locator("input[name='username']").count() > 0)

    def _read_login_error(self) -> str | None:
        for snippet in (
            INCORRECT_CREDENTIALS_SNIPPET,
            ACCOUNT_LOCKED_SNIPPET,
            "Username required",
            "Password required",
        ):
            locator = self._portal.get_by_text(snippet, exact=False)
            text = self._first_visible_text(locator)
            if text:
                return text
        return None

    @staticmethod
    def _first_visible_text(locator: Locator) -> str | None:
        for index in range(locator.count()):
            text = locator.nth(index).inner_text(timeout=200).strip()
            if text:
                return text
        return None
