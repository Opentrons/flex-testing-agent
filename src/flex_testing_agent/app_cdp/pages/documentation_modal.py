"""Documentation Required modal after forced password reset (CRS audit note)."""

from __future__ import annotations

import os
import time

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from flex_testing_agent.app_cdp.base import click_portal_confirm, portal

DOCUMENTATION_REQUIRED_HEADING = "Documentation required"
CANCEL_ACTION_LABEL = "Cancel action"


def default_audit_note() -> str:
    """Default audit note for App mutations (matches HTTP ``ROBOT_USER_NOTES``)."""
    return os.environ.get("ROBOT_USER_NOTES", "").strip() or (
        "flex-testing-agent CRS App flow"
    )


class DocumentationModalPage:
    """CRS documentation / reason-for-interaction modal in the top portal."""

    def __init__(self, page: Page) -> None:
        self._page = page
        self._portal = portal(page)

    def is_open(self) -> bool:
        heading = self._portal.get_by_text(
            DOCUMENTATION_REQUIRED_HEADING,
            exact=False,
        )
        return bool(heading.count() > 0)

    def wait_for_open(self, *, timeout_ms: float = 10_000) -> None:
        deadline = time.time() + (timeout_ms / 1000)
        while time.time() < deadline:
            if self.is_open():
                return
            self._page.wait_for_timeout(200)
        msg = "Timed out waiting for Documentation required modal"
        raise PlaywrightTimeoutError(msg)

    def fill_note(self, note: str) -> None:
        """Fill the audit note textarea (Confirm stays disabled until non-empty)."""
        field = self._portal.locator("textarea").first
        field.wait_for(state="visible", timeout=10_000)
        field.fill(note)

    def confirm(self, *, note: str | None = None) -> None:
        """Enter an audit note and submit the documentation modal."""
        self.wait_for_open()
        self.fill_note(note or default_audit_note())
        click_portal_confirm(self._portal, label="Confirm")
