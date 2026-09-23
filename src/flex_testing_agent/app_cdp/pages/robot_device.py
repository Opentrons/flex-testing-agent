"""Robot device overview page object."""

from __future__ import annotations

import time

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from flex_testing_agent.app_cdp.base import (
    hash_path,
    hash_route,
    open_devices_tab,
    wait_for_visible_text,
)
from flex_testing_agent.app_cdp.pages.login_modal import LoginModalPage

ROBOT_OVERFLOW_MENU_TEST_ID = "RobotOverview_overflowMenu"
ROBOT_SETTINGS_MENU_ITEM = "Robot settings"
OVERFLOW_MENU_ANCHOR_TEXT = "Run a protocol"


class RobotDevicePage:
    """Single robot view under Devices (``#/devices/:robotName``)."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def open(self, robot_name: str) -> None:
        """Navigate to the robot device overview (not settings subroutes)."""
        open_devices_tab(self._page)
        target = f"/devices/{robot_name}"
        current = hash_path(self._page)
        if current != target:
            hash_route(self._page, target)
        wait_for_visible_text(self._page, robot_name, exact=True, timeout_ms=30_000)

    def open_login_modal(self) -> LoginModalPage:
        modal = LoginModalPage(self._page)
        if modal.is_open:
            return modal

        login = self._page.get_by_role("button", name="Log in")
        if login.count() == 0:
            login = self._page.get_by_test_id("basic_button_Log in")
        if login.count() == 0:
            login = self._page.get_by_text("Log in", exact=True)
        login.first.click()
        modal.wait_for_login_form()
        return modal

    def is_logged_in(self) -> bool:
        if self._page.get_by_text("Log out", exact=False).count() > 0:
            return True
        if LoginModalPage(self._page).is_open:
            return False
        login = self._page.get_by_role("button", name="Log in")
        if login.count() > 0 and login.first.is_visible():
            return False
        return hash_path(self._page).startswith("/devices/")

    def _overflow_menu_open(self) -> bool:
        anchor = self._page.get_by_text(OVERFLOW_MENU_ANCHOR_TEXT, exact=True)
        settings = self._page.get_by_text(ROBOT_SETTINGS_MENU_ITEM, exact=True)
        return anchor.count() > 0 and settings.count() > 0

    def _open_overflow_menu(self) -> None:
        if self._overflow_menu_open():
            return
        overflow = self._page.get_by_test_id(ROBOT_OVERFLOW_MENU_TEST_ID)
        if overflow.count() == 0:
            overflow = self._page.get_by_role("button", name="overflow")
        overflow.first.wait_for(state="visible", timeout=10_000)
        overflow.first.click()
        self._page.get_by_text(OVERFLOW_MENU_ANCHOR_TEXT, exact=True).first.wait_for(
            state="visible",
            timeout=10_000,
        )

    def open_robot_settings(self) -> None:
        """Open Robot settings from the robot card overflow (⋮) menu."""
        if "robot-settings" in hash_path(self._page):
            return
        self._open_overflow_menu()
        settings_entry = self._page.get_by_text(ROBOT_SETTINGS_MENU_ITEM, exact=True)
        settings_entry.last.wait_for(state="visible", timeout=10_000)
        settings_entry.last.click()
        deadline = time.time() + 15
        while time.time() < deadline:
            if "robot-settings" in hash_path(self._page):
                return
            self._page.wait_for_timeout(250)
        msg = "Timed out waiting for robot-settings route"
        raise PlaywrightTimeoutError(msg)
