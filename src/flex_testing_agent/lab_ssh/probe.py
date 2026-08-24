"""TCP and OpenSSH probes for the lab robot (root @ ROBOT_HOST)."""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.logging import get_logger

log = get_logger(__name__)

DEFAULT_IDENTITY = Path.home() / ".ssh" / "robot_key"


@dataclass(frozen=True, slots=True)
class LabSshStatus:
    """Reachability of lab SSH (port 22), optional BatchMode auth."""

    host: str
    port: int
    tcp_reachable: bool
    authenticated: bool | None
    identity_path: Path | None
    detail: str


def resolved_ssh_identity(settings: Settings) -> Path | None:
    """Return a usable private key path, or None if missing."""
    configured = settings.robot_ssh_identity
    if configured is not None:
        path = configured.expanduser()
        return path if path.is_file() else None
    if DEFAULT_IDENTITY.is_file():
        return DEFAULT_IDENTITY
    return None


def ssh_argv(
    settings: Settings,
    remote_command: str,
    *,
    identity: Path | None = None,
) -> list[str]:
    """Build an ``ssh`` argv for a single remote command (BatchMode)."""
    host = settings.require_robot_host()
    key = identity if identity is not None else resolved_ssh_identity(settings)
    timeout = max(1, int(settings.robot_ssh_timeout_seconds))
    argv: list[str] = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        "IdentitiesOnly=yes",
        "-p",
        str(settings.robot_ssh_port),
    ]
    if key is not None:
        argv.extend(["-i", str(key)])
    argv.append(f"{settings.robot_ssh_user}@{host}")
    argv.append(remote_command)
    return argv


async def probe_tcp_port(host: str, port: int, *, timeout: float) -> bool:
    """Return True if TCP connect to ``host:port`` succeeds."""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


def run_lab_ssh(
    settings: Settings,
    remote_command: str,
    *,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Run ``remote_command`` over SSH. Return None if ssh cannot start.

    Non-zero exit is still a completed process (caller inspects returncode).
    """
    identity = resolved_ssh_identity(settings)
    if identity is None and settings.robot_ssh_identity is not None:
        log.info("ssh_identity_missing", path=str(settings.robot_ssh_identity))
    argv = ssh_argv(settings, remote_command, identity=identity)
    wait = timeout if timeout is not None else settings.robot_ssh_timeout_seconds + 2.0
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=wait,
        )
    except FileNotFoundError:
        log.info("ssh_binary_missing")
        return None
    except subprocess.TimeoutExpired:
        log.info("ssh_timeout", host=settings.robot_host)
        return None


async def probe_lab_ssh(settings: Settings) -> LabSshStatus:
    """Probe TCP :22 then BatchMode ``true`` when a key exists."""
    host = settings.require_robot_host()
    port = settings.robot_ssh_port
    timeout = min(settings.robot_ssh_timeout_seconds, 5.0)
    tcp = await probe_tcp_port(host, port, timeout=timeout)
    identity = resolved_ssh_identity(settings)
    if not tcp:
        return LabSshStatus(
            host=host,
            port=port,
            tcp_reachable=False,
            authenticated=None,
            identity_path=identity,
            detail="TCP connect to SSH port failed (CRS-on lockout, or network).",
        )
    if identity is None:
        return LabSshStatus(
            host=host,
            port=port,
            tcp_reachable=True,
            authenticated=None,
            identity_path=None,
            detail="SSH port open; no lab key (ROBOT_SSH_IDENTITY / ~/.ssh/robot_key).",
        )
    completed = await asyncio.to_thread(run_lab_ssh, settings, "true")
    if completed is None:
        return LabSshStatus(
            host=host,
            port=port,
            tcp_reachable=True,
            authenticated=False,
            identity_path=identity,
            detail="ssh binary missing or timed out after TCP connect.",
        )
    ok = completed.returncode == 0
    err = (completed.stderr or completed.stdout or "").strip()
    detail = "BatchMode SSH authenticated." if ok else (err[-400:] or "ssh non-zero")
    return LabSshStatus(
        host=host,
        port=port,
        tcp_reachable=True,
        authenticated=ok,
        identity_path=identity,
        detail=detail,
    )
