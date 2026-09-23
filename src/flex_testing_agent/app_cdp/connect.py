"""Launch or attach to the Opentrons desktop app over CDP."""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

from flex_testing_agent.app_cdp.discovery import get_opentrons_app_path

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page, Playwright

DEFAULT_CDP_PORT = 9222
CDP_READY_TIMEOUT_S = 30.0


def resolve_cdp_endpoint(
    *,
    host: str | None = None,
    port: int | None = None,
) -> tuple[str, int]:
    """Resolve CDP host/port from args or ``CDP_HOST`` / ``CDP_PORT`` env vars."""
    resolved_host = (
        host or os.environ.get("CDP_HOST", "").strip() or "127.0.0.1"
    ).strip()
    if port is not None:
        resolved_port = port
    else:
        env_port = os.environ.get("CDP_PORT", "").strip()
        resolved_port = int(env_port) if env_port else DEFAULT_CDP_PORT
    return resolved_host, resolved_port


def cdp_is_ready(debug_port: int, *, host: str = "127.0.0.1") -> bool:
    """Return True when something is listening on the CDP port."""
    url = f"http://{host}:{debug_port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=1):
            return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _wait_for_cdp(
    debug_port: int,
    timeout: float = CDP_READY_TIMEOUT_S,
    *,
    host: str = "127.0.0.1",
) -> None:
    url = f"http://{host}:{debug_port}/json/version"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5)
    msg = f"CDP not ready at {host}:{debug_port} after {timeout}s"
    raise TimeoutError(msg)


def _electron_launch_env() -> dict[str, str]:
    # Cursor / VS Code set ELECTRON_RUN_AS_NODE=1, which makes Electron reject
    # Chromium flags like --remote-debugging-port.
    return {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}


def launch_app(
    *,
    debug_port: int = DEFAULT_CDP_PORT,
    quiet: bool = True,
    log_file: Path | None = None,
) -> subprocess.Popen[bytes]:
    """Launch Opentrons with remote debugging. Returns once CDP is up."""
    app_path = get_opentrons_app_path()
    stdout_target: int | IO[str] | None = None
    stderr_target: int | IO[str] | None = None
    log_handle: IO[str] | None = None
    if quiet and log_file is None:
        stdout_target = subprocess.DEVNULL
        stderr_target = subprocess.DEVNULL
    elif log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_file.open("w", encoding="utf-8")
        stdout_target = log_handle
        stderr_target = log_handle

    process = subprocess.Popen(
        [str(app_path), f"--remote-debugging-port={debug_port}"],
        env=_electron_launch_env(),
        stdout=stdout_target,
        stderr=stderr_target,
    )
    _wait_for_cdp(debug_port)
    if log_handle is not None:
        log_handle.flush()
    return process


def _require_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError as exc:
        msg = (
            "Playwright is required for CDP attach. Install with: "
            "uv sync --extra app && uv run playwright install chromium"
        )
        raise RuntimeError(msg) from exc


def _is_app_page(page: Page) -> bool:
    url = page.url.lower()
    title = page.title().lower()
    if "devtools" in url or title == "devtools":
        return False
    return "index.html" in url or "opentrons" in title


def _iter_cdp_pages(browser: Browser) -> Iterator[Page]:
    for context in browser.contexts:
        yield from context.pages


def _find_app_page(browser: Browser) -> Page:
    for _ in range(30):
        for page in _iter_cdp_pages(browser):
            if _is_app_page(page):
                return page
        time.sleep(1)

    for page in _iter_cdp_pages(browser):
        if "devtools" not in page.url.lower():
            return page

    msg = "Could not find Opentrons app window"
    raise RuntimeError(msg)


@dataclass
class AppCdpConnection:
    """Live Playwright attach to the Opentrons desktop app."""

    playwright: Playwright
    browser: Browser
    page: Page
    process: subprocess.Popen[bytes] | None = None

    def close(self) -> None:
        self.browser.close()
        self.playwright.stop()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()


def connect_playwright(
    *,
    debug_port: int | None = None,
    host: str | None = None,
) -> AppCdpConnection:
    """Connect Playwright to a running Opentrons app. Caller must close()."""
    _require_playwright()
    from playwright.sync_api import sync_playwright

    cdp_host, cdp_port = resolve_cdp_endpoint(host=host, port=debug_port)
    playwright = sync_playwright().start()
    cdp_url = f"http://{cdp_host}:{cdp_port}"
    browser = playwright.chromium.connect_over_cdp(cdp_url)
    page = _find_app_page(browser)
    with contextlib.suppress(Exception):
        page.bring_to_front()
    with contextlib.suppress(Exception):
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
    return AppCdpConnection(playwright=playwright, browser=browser, page=page)


def attach_to_app(
    *,
    debug_port: int | None = None,
    host: str | None = None,
) -> AppCdpConnection:
    """Attach to an already-running Opentrons app with CDP enabled."""
    cdp_host, cdp_port = resolve_cdp_endpoint(host=host, port=debug_port)
    if not cdp_is_ready(cdp_port, host=cdp_host):
        msg = (
            f"CDP not reachable at http://{cdp_host}:{cdp_port}/json/version. "
            "Launch the app with remote debugging (flex-test app launch) or "
            "restart an existing instance with --remote-debugging-port."
        )
        raise TimeoutError(msg)
    return connect_playwright(host=cdp_host, debug_port=cdp_port)


def launch_and_attach(
    *,
    debug_port: int = DEFAULT_CDP_PORT,
    quiet: bool = True,
    log_file: Path | None = None,
) -> AppCdpConnection:
    """Launch the packaged Opentrons app (or attach if CDP is already up)."""
    if cdp_is_ready(debug_port):
        connection = connect_playwright(debug_port=debug_port)
        return connection

    process = launch_app(debug_port=debug_port, quiet=quiet, log_file=log_file)
    connection = connect_playwright(debug_port=debug_port)
    # Cold launch: index shell can take a few seconds before hash routes render.
    connection.page.wait_for_load_state("domcontentloaded", timeout=30_000)
    connection.process = process
    return connection
