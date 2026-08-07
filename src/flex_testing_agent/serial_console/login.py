"""Login helpers for the Flex serial console."""

from __future__ import annotations

import time
from dataclasses import dataclass

from flex_testing_agent.serial_console.constants import DEFAULT_LOGIN_USER
from flex_testing_agent.serial_console.errors import LoginError
from flex_testing_agent.serial_console.kernel_log import partition_console_text
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


def _normalize_serial_text(text: str) -> str:
    """Normalize CR/LF so marker search survives serial echo quirks."""
    return text.replace("\r\n", "\n").replace("\r", "")


def _extract_marked_body(text: str, start_tok: str, end_tok: str) -> str | None:
    """Return lines between echo markers (markers alone on a line)."""
    lines = text.split("\n")
    start_i: int | None = None
    end_i: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == start_tok and start_i is None:
            start_i = i
        elif stripped == end_tok and start_i is not None:
            end_i = i
            break
    if start_i is None or end_i is None:
        return None
    return "\n".join(lines[start_i + 1 : end_i])


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Result of a scripted serial command, with kernel lines retained.

    ``output`` is the command body with printk lines removed (stable for
    automation). ``kernel_lines`` and ``raw`` keep the Confluence-documented
    kernel console stream for boot / driver debugging.
    """

    output: str
    kernel_lines: tuple[str, ...]
    raw: str
    marked_body: str | None


def run_command_result(
    session: SerialSession,
    command: str,
    *,
    timeout: float = 30.0,
    login: bool = True,
) -> CommandResult:
    """Run ``command`` and return partitioned command vs kernel output."""
    if login:
        ensure_logged_in(session, timeout=min(15.0, timeout))

    # Compact marker: long echo lines get mid-line CR on some Flex consoles.
    marker = f"FTA{int(time.time() * 1000) % 1_000_000_000}"
    start_tok = f"__{marker}__"
    end_tok = f"__{marker}_END__"
    session.write_line(f"echo {start_tok}; {command}; echo {end_tok}")
    raw = session.read_until(time.monotonic() + timeout)
    text = _normalize_serial_text(raw)
    body = _extract_marked_body(text, start_tok, end_tok)
    source = body if body is not None else text
    parts = partition_console_text(source)
    # Kernel lines from the full transcript (including outside markers).
    full_parts = partition_console_text(text)
    return CommandResult(
        output=parts.other_text.strip("\n"),
        kernel_lines=full_parts.kernel_lines,
        raw=text,
        marked_body=body,
    )


def run_command(
    session: SerialSession,
    command: str,
    *,
    timeout: float = 30.0,
    login: bool = True,
) -> str:
    """Optionally log in, run ``command``, and return command-only output.

    Kernel printk lines are stripped from the returned string but remain
    available via :func:`run_command_result` (see docs/serial-console.md).
    """
    return run_command_result(
        session,
        command,
        timeout=timeout,
        login=login,
    ).output


def watch_console(
    session: SerialSession,
    *,
    seconds: float,
) -> str:
    """Read the serial console for ``seconds`` without sending commands.

    Captures bootloader / kernel / shell noise as-is. Useful while powering
    the Flex or waiting for printk during USB / driver events.
    """
    if seconds <= 0:
        return ""
    deadline = time.monotonic() + seconds
    buf = bytearray()
    while time.monotonic() < deadline:
        chunk = session.read_available()
        if chunk:
            buf.extend(chunk)
        else:
            time.sleep(0.05)
    chunk = session.read_available()
    if chunk:
        buf.extend(chunk)
    return _normalize_serial_text(buf.decode("utf-8", errors="replace"))
