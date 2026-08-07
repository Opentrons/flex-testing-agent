"""Login helpers for the Flex serial console."""

from __future__ import annotations

import time

from flex_testing_agent.serial_console.constants import DEFAULT_LOGIN_USER
from flex_testing_agent.serial_console.errors import LoginError
from flex_testing_agent.serial_console.session import (
    SerialSession,
    detect_console_state,
)


def probe_console_state(
    session: SerialSession,
    *,
    timeout: float = 3.0,
) -> tuple[str, str]:
    """Hit Enter a few times and classify the resulting prompt.

    Returns ``(state, captured_text)`` where state is one of
    ``login``, ``password``, ``shell``, or ``unknown``.
    """
    session.write_bytes(b"\r")
    time.sleep(0.1)
    session.write_bytes(b"\n")
    text = session.read_until(time.monotonic() + timeout)
    state = detect_console_state(text)
    if state == "unknown":
        # Second nudge: common when kernel logs buried the prompt.
        session.write_bytes(b"\n")
        more = session.read_until(time.monotonic() + timeout)
        text = text + more
        state = detect_console_state(text)
    return state, text


def ensure_logged_in(
    session: SerialSession,
    *,
    user: str = DEFAULT_LOGIN_USER,
    timeout: float = 10.0,
) -> str:
    """Ensure a root shell is available; auto-login when at a login prompt.

    Returns the last captured console text. Raises ``LoginError`` on failure.
    """
    deadline = time.monotonic() + timeout
    last_text = ""
    attempts = 0
    while time.monotonic() < deadline and attempts < 8:
        attempts += 1
        remaining = max(0.5, deadline - time.monotonic())
        state, text = probe_console_state(session, timeout=min(3.0, remaining))
        last_text = text
        if state == "shell":
            return text
        if state == "password":
            # Typo / accidental password prompt: Escape with Enter and retry.
            session.write_bytes(b"\n")
            session.drain(0.5)
            continue
        if state == "login":
            session.write_line(user)
            after = session.read_until(
                time.monotonic() + min(5.0, deadline - time.monotonic())
            )
            last_text = after
            after_state = detect_console_state(after)
            if after_state == "shell":
                return after
            if after_state == "password":
                session.write_bytes(b"\n")
                session.drain(0.5)
                continue
            # Already logged in sometimes echoes oddly; probe again.
            continue
        # unknown: keep probing
        time.sleep(0.3)

    raise LoginError(
        "Could not obtain a Flex serial shell prompt "
        f"(tried login as {user!r}). Last output:\n{last_text[-2000:]}"
    )


def run_command(
    session: SerialSession,
    command: str,
    *,
    timeout: float = 30.0,
    login: bool = True,
) -> str:
    """Optionally log in, run ``command``, and return captured output.

    Output collection stops when a shell prompt reappears or ``timeout`` hits.
    Kernel log lines may interleave (expected on the Flex console).
    """
    if login:
        ensure_logged_in(session, timeout=min(15.0, timeout))

    # Marker makes it easier to slice command output from prior banner noise.
    marker = f"__FTA_CMD_{int(time.time() * 1000)}__"
    session.write_line(f"echo {marker}; {command}; echo {marker}_END")
    raw = session.read_until(time.monotonic() + timeout)
    start = raw.find(marker)
    end = raw.find(f"{marker}_END")
    if start != -1 and end != -1 and end > start:
        body = raw[start + len(marker) : end]
        # Drop the echo line's trailing newline / prompt fragments.
        return body.lstrip("\r\n")
    return raw
