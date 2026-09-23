"""Compliance Ready robot settings page object."""

from __future__ import annotations

import time

from playwright.sync_api import Locator, Page

from flex_testing_agent.app_cdp.base import hash_path
from flex_testing_agent.app_cdp.pages.robot_device import RobotDevicePage
from flex_testing_agent.app_cdp.settings_validation import (
    AppAuditSettingsSnapshot,
    AppAuthSettingsSnapshot,
)

COMPLIANCE_READY_TAB = "Compliance Ready"
USER_MANAGEMENT_TITLE = "User management"
USER_MANAGEMENT_PANEL_ID = "user-management"
SOFTWARE_SETTINGS_TITLE = "Compliance Ready Software settings"
SOFTWARE_SETTINGS_PANEL_ID = "compliance-ready-software-settings"
DESKTOP_USERNAME_HEADER = "Username"
USER_MANAGEMENT_TABLE = '[data-sentry-component="UserManagementTable"]'
USER_MANAGEMENT_ROW_TEST_ID = "ListItem_default"

PASSWORD_RESET_ENABLED_ID = "passwordResetEnabled"
PASSWORD_COMPLEXITY_ENABLED_ID = "passwordComplexityEnabled"
REQUIRE_ADMIN_UPDATE_ID = "requireAdminCredsWhenUpdatingRobotSoftware"
REQUIRE_ADMIN_PROTOCOL_ID = "requireAdminCredsWhenSendingProtocolToRobot"
REQUIRE_ADMIN_SIGNOFF_ID = "requireAdminCredsForSignoffProtocol"
REQUIRE_REASON_ID = "requireReasonForInteraction"

MAX_LOGIN_ATTEMPTS_LABEL = "Maximum login attempts before account deactivation"
IDLE_LOGOUT_LABEL = "Length of time for auto-logout due to inactivity"
PASSWORD_RESET_TIME_LABEL = "Length of time before password must be changed"
PASSWORD_MIN_LENGTH_LABEL = "Minimum password length"
PASSWORD_SPECIAL_CHARS_LABEL = "Require special characters in password"


class ComplianceSettingsPage:
    """Robot settings → Compliance Ready tab (via robot card overflow menu)."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def open(self, robot_name: str) -> None:
        device_prefix = f"/devices/{robot_name}"
        compliance_route = f"{device_prefix}/robot-settings/compliance-ready"
        current = hash_path(self._page)

        if current.startswith(compliance_route):
            self._page.get_by_text(COMPLIANCE_READY_TAB, exact=False).first.wait_for(
                state="visible",
                timeout=15_000,
            )
            return

        robot = RobotDevicePage(self._page)
        if not current.startswith(f"{device_prefix}/robot-settings"):
            robot.open(robot_name)
            robot.open_robot_settings()

        tab = self._page.get_by_role("tab", name=COMPLIANCE_READY_TAB)
        if tab.count() == 0:
            tab = self._page.get_by_text(COMPLIANCE_READY_TAB, exact=False)
        selected = tab.first.get_attribute("aria-selected")
        if selected != "true":
            tab.first.click()
        self._page.get_by_text(COMPLIANCE_READY_TAB, exact=False).first.wait_for(
            state="visible",
            timeout=15_000,
        )

    def _user_management_panel(self) -> Locator:
        return self._page.locator(f"#{USER_MANAGEMENT_PANEL_ID}")

    def _user_management_rows(self) -> Locator:
        return self._user_management_panel().locator(
            f'[data-testid="{USER_MANAGEMENT_ROW_TEST_ID}"]'
        )

    def _accordion_button(self, title: str) -> Locator:
        accordion = self._page.get_by_role("button", name=title)
        if accordion.count() == 0:
            accordion = self._page.locator("button").filter(
                has=self._page.get_by_text(title, exact=False),
            )
        return accordion.first

    def _expand_accordion(self, title: str, *, panel_id: str) -> Locator:
        header = self._accordion_button(title)
        if header.get_attribute("aria-expanded") != "true":
            header.click()
        panel = self._page.locator(f"#{panel_id}")
        panel.wait_for(state="visible", timeout=10_000)
        return panel

    def open_user_management(self) -> None:
        panel = self._expand_accordion(
            USER_MANAGEMENT_TITLE,
            panel_id=USER_MANAGEMENT_PANEL_ID,
        )
        table = panel.locator(USER_MANAGEMENT_TABLE)
        if table.count() > 0:
            table.first.wait_for(state="visible", timeout=10_000)
        else:
            panel.get_by_text(DESKTOP_USERNAME_HEADER, exact=True).first.wait_for(
                state="visible",
                timeout=10_000,
            )
        self._user_management_rows().first.wait_for(state="visible", timeout=10_000)

    def _software_settings_expanded(self) -> bool:
        return (
            self._accordion_button(SOFTWARE_SETTINGS_TITLE).get_attribute(
                "aria-expanded",
            )
            == "true"
        )

    def open_software_settings(self) -> None:
        """Expand the Compliance Ready Software settings accordion section."""
        if not self._software_settings_expanded():
            self._expand_accordion(
                SOFTWARE_SETTINGS_TITLE,
                panel_id=SOFTWARE_SETTINGS_PANEL_ID,
            )

        # Initial expand can leave duplicate InputSetting skeleton rows in the
        # DOM; collapse and re-expand matches the manual workaround.
        header = self._accordion_button(SOFTWARE_SETTINGS_TITLE)
        if self._software_settings_expanded():
            header.click()
            self._page.wait_for_timeout(1_000)
        panel = self._expand_accordion(
            SOFTWARE_SETTINGS_TITLE,
            panel_id=SOFTWARE_SETTINGS_PANEL_ID,
        )
        panel.get_by_text("Login and security", exact=False).first.wait_for(
            state="visible",
            timeout=10_000,
        )
        # Settings hydrate from the robot API shortly after the accordion opens.
        self._page.wait_for_timeout(2_000)

    def _software_settings_panel(self) -> Locator:
        return self._page.locator(f"#{SOFTWARE_SETTINGS_PANEL_ID}")

    def _switch_checked(self, element_id: str) -> bool:
        switch = self._page.locator(f"#{element_id}")
        switch.wait_for(state="visible", timeout=10_000)
        return switch.get_attribute("aria-checked") == "true"

    def _read_number_input(
        self,
        field: Locator,
        *,
        timeout_ms: float = 15_000,
    ) -> float | None:
        field.wait_for(state="visible", timeout=timeout_ms)
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            raw = (field.input_value() or field.get_attribute("value") or "").strip()
            if raw:
                return float(raw)
            self._page.wait_for_timeout(200)
        return None

    def _number_input_in_panel(
        self,
        panel: Locator,
        label: str,
        *,
        timeout_ms: float = 15_000,
    ) -> float | None:
        rows = panel.locator('[data-sentry-component="InputSetting"]').filter(
            has_text=label,
        )
        if rows.count() == 0:
            return None
        for index in range(rows.count()):
            field = rows.nth(index).locator('input[type="number"]')
            if field.count() == 0:
                continue
            value = self._read_number_input(field.first, timeout_ms=timeout_ms)
            if value is not None:
                return value
        return None

    def read_auth_settings_snapshot(self) -> AppAuthSettingsSnapshot:
        """Read auth settings from the expanded software settings panel."""
        if not self._software_settings_expanded():
            self.open_software_settings()
        panel = self._software_settings_panel()

        max_attempts = self._number_input_in_panel(panel, MAX_LOGIN_ATTEMPTS_LABEL)
        if max_attempts is None:
            msg = f"Could not read {MAX_LOGIN_ATTEMPTS_LABEL!r} from App UI"
            raise RuntimeError(msg)

        password_reset_enabled = self._switch_checked(PASSWORD_RESET_ENABLED_ID)
        password_reset_time = (
            self._number_input_in_panel(panel, PASSWORD_RESET_TIME_LABEL)
            if password_reset_enabled
            else None
        )

        password_complexity_enabled = self._switch_checked(
            PASSWORD_COMPLEXITY_ENABLED_ID,
        )
        password_complexity_minimum_length = (
            int(length)
            if (length := self._number_input_in_panel(panel, PASSWORD_MIN_LENGTH_LABEL))
            is not None
            else None
        )
        password_complexity_special_characters = (
            self._switch_checked("passwordComplexitySpecialCharacters")
            if panel.locator("#passwordComplexitySpecialCharacters").count() > 0
            else None
        )
        if (
            password_complexity_enabled
            and password_complexity_special_characters is None
        ):
            # App may expose complexity as a single master toggle without sub-switches.
            password_complexity_special_characters = (
                True if password_complexity_minimum_length is not None else None
            )

        idle_logout = self._number_input_in_panel(panel, IDLE_LOGOUT_LABEL)
        if idle_logout is None:
            msg = f"Could not read {IDLE_LOGOUT_LABEL!r} from App UI"
            raise RuntimeError(msg)

        return AppAuthSettingsSnapshot(
            max_number_of_login_attempts=int(max_attempts),
            password_reset_enabled=password_reset_enabled,
            password_reset_time=password_reset_time,
            password_complexity_enabled=password_complexity_enabled,
            password_complexity_minimum_length=password_complexity_minimum_length,
            password_complexity_special_characters=password_complexity_special_characters,
            idle_logout_minutes=idle_logout,
            require_admin_creds_when_updating_robot_software=self._switch_checked(
                REQUIRE_ADMIN_UPDATE_ID,
            ),
            require_admin_creds_when_sending_protocol_to_robot=self._switch_checked(
                REQUIRE_ADMIN_PROTOCOL_ID,
            ),
            require_admin_creds_for_signoff_protocol=self._switch_checked(
                REQUIRE_ADMIN_SIGNOFF_ID,
            ),
        )

    def read_audit_settings_snapshot(self) -> AppAuditSettingsSnapshot:
        """Read audit settings toggles from the expanded software settings panel."""
        if not self._software_settings_expanded():
            self.open_software_settings()
        return AppAuditSettingsSnapshot(
            require_reason_for_interaction=self._switch_checked(REQUIRE_REASON_ID),
        )

    def usernames_visible(self) -> list[str]:
        self.open_user_management()
        rows = self._user_management_rows()
        names: list[str] = []
        for index in range(rows.count()):
            first_cell = rows.nth(index).locator("p").first
            name = first_cell.inner_text(timeout=1_000).strip()
            if name:
                names.append(name)
        return names

    def expects_username(self, username: str) -> bool:
        return username in self.usernames_visible()
