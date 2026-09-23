"""Shared helpers for Opentrons desktop app page objects."""

from __future__ import annotations

import time

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

PORTAL_TEST_ID = "__otAppTopPortalRoot"


def app_base_url(page: Page) -> str:
    """Return the app index URL without the hash route."""
    url = page.url
    if "#" in url:
        return url.split("#", 1)[0]
    return url


def hash_path(page: Page) -> str:
    """Return the hash route path (leading slash) for the current page."""
    url = page.url
    if "#" not in url:
        return "/"
    path = url.split("#", 1)[1]
    return path if path.startswith("/") else f"/{path}"


def hash_route(page: Page, path: str) -> None:
    """Navigate to a hash route under the current app index."""
    normalized = path if path.startswith("/") else f"/{path}"
    current = hash_path(page)
    if current == normalized:
        return
    page.goto(f"{app_base_url(page)}#{normalized}")


def open_devices_tab(page: Page, *, timeout_ms: float = 15_000) -> None:
    """Select the Devices item in the App left navigation."""
    if hash_path(page).startswith("/devices"):
        return

    candidates = (
        page.get_by_role("link", name="Devices"),
        page.get_by_role("button", name="Devices"),
        page.locator("a").filter(has_text="Devices"),
    )
    clicked = False
    for locator in candidates:
        if locator.count() == 0:
            continue
        for index in range(locator.count()):
            item = locator.nth(index)
            if item.is_visible():
                item.click()
                clicked = True
                break
        if clicked:
            break

    if not clicked:
        wait_for_visible_text(page, "Devices", exact=True, timeout_ms=5_000).click()

    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        if hash_path(page).startswith("/devices"):
            return
        page.wait_for_timeout(250)

    msg = "Timed out waiting for Devices tab navigation"
    raise PlaywrightTimeoutError(msg)


def portal(page: Page) -> Locator:
    """Top portal root where modals (login, etc.) render."""
    return page.get_by_test_id(PORTAL_TEST_ID)


def portal_form_submit_button(
    portal_root: Locator,
    *,
    label: str = "Confirm",
) -> Locator:
    """Submit button for the active portal modal form.

    Stacked App modals may render a disabled primary Confirm above the real
    ``type="submit"`` control on the underlying form. Target submit explicitly.
    """
    return portal_root.locator("button[type='submit']", has_text=label)


def click_portal_confirm(
    portal_root: Locator,
    *,
    label: str = "Confirm",
    timeout_ms: float = 30_000,
) -> None:
    """Click the enabled Confirm control in a portal modal."""
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        submit = portal_root.locator("button[type='submit']", has_text=label)
        if submit.count() > 0 and submit.first.is_enabled():
            submit.first.click()
            return
        enabled = portal_root.get_by_role("button", name=label, disabled=False)
        if enabled.count() > 0:
            enabled.last.click()
            return
        portal_root.page.wait_for_timeout(250)
    msg = f"Timed out clicking enabled portal {label!r} button"
    raise PlaywrightTimeoutError(msg)


def wait_for_visible_text(
    page: Page,
    text: str,
    *,
    exact: bool = True,
    timeout_ms: float = 15_000,
) -> Locator:
    """Wait until at least one matching text node is visible."""
    locator = page.get_by_text(text, exact=exact)
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        for index in range(locator.count()):
            candidate = locator.nth(index)
            if candidate.is_visible():
                return candidate
        page.wait_for_timeout(250)
    msg = f"Timed out waiting for visible text {text!r}"
    raise PlaywrightTimeoutError(msg)
