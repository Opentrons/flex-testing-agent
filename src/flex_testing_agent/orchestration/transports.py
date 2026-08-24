"""Assess HTTP(S) vs SSH vs serial after inspect / CRS detect.

See docs/interaction-layers.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.lab_ssh.probe import LabSshStatus, probe_lab_ssh, run_lab_ssh
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.access_control import AccessControlState
from flex_testing_agent.models.snapshot import RobotSnapshot
from flex_testing_agent.orchestration.discover import probe_robot_host
from flex_testing_agent.serial_console.remote_access import (
    STATUS_REMOTE_ACCESS_SHELL,
    RemoteAccessStatus,
    parse_remote_access_status,
    probe_remote_access,
)
from flex_testing_agent.serial_console.session import SerialSession

log = get_logger(__name__)

ShellTransport = Literal["ssh", "serial", "none", "unknown"]

RQA_5981 = "https://opentrons.atlassian.net/browse/RQA-5981"


@dataclass(frozen=True, slots=True)
class TransportAssessment:
    """How to talk to the robot after a live inspect."""

    api_scheme: str
    api_base_url: str
    crs_on: bool
    plaintext_http_reachable: bool | None
    ssh: LabSshStatus | None
    recommended_shell: ShellTransport
    notes: tuple[str, ...]

    def as_evidence(self) -> dict[str, object]:
        """JSON-serializable inspect evidence."""
        ssh: dict[str, object] | None = None
        if self.ssh is not None:
            ssh = {
                "host": self.ssh.host,
                "port": self.ssh.port,
                "tcp_reachable": self.ssh.tcp_reachable,
                "authenticated": self.ssh.authenticated,
                "identity_path": (
                    str(self.ssh.identity_path) if self.ssh.identity_path else None
                ),
                "detail": self.ssh.detail,
            }
        return {
            "api_scheme": self.api_scheme,
            "api_base_url": self.api_base_url,
            "crs_on": self.crs_on,
            "plaintext_http_reachable": self.plaintext_http_reachable,
            "ssh": ssh,
            "recommended_shell": self.recommended_shell,
            "notes": list(self.notes),
            "plaintext_http_ticket": RQA_5981,
        }


@dataclass(frozen=True, slots=True)
class CarveoutProbe:
    """Remote-access sentinel probe, SSH preferred over serial."""

    transport: Literal["ssh", "serial"]
    status: RemoteAccessStatus


async def probe_plaintext_http_health(settings: Settings) -> bool | None:
    """True if GET /health on HTTP :31950 returns JSON (CRS-on leak check)."""
    host = settings.require_robot_host()
    timeout = min(settings.robot_health_timeout_seconds, 3.0)
    payload = await probe_robot_host(
        host,
        port=settings.robot_http_port,
        use_https=False,
        timeout_seconds=timeout,
        expected_name=None,
        verify=True,
    )
    return payload is not None


def _recommended_shell(ssh: LabSshStatus | None) -> ShellTransport:
    if ssh is None:
        return "unknown"
    if ssh.authenticated is True:
        return "ssh"
    return "serial"


async def assess_transports(
    settings: Settings,
    snapshot: RobotSnapshot,
) -> TransportAssessment:
    """Probe plaintext HTTP (CRS on) and lab SSH. Never uses HTTP for CRS API."""
    crs_on = snapshot.access_control.state == AccessControlState.ENABLED
    notes: list[str] = [
        f"API {snapshot.base_url} ({'HTTPS' if settings.robot_use_https else 'HTTP'})."
    ]
    plaintext: bool | None = None
    if crs_on:
        notes.append(
            "CRS is on: use HTTPS :32313 for all flex-test API calls. "
            f"Do not send credentials on :31950 ({RQA_5981})."
        )
        plaintext = await probe_plaintext_http_health(settings)
        if plaintext:
            notes.append(
                "Plaintext HTTP :31950 still answered GET /health. Product leak; "
                "harness stays on HTTPS."
            )
            log.warning(
                "inspect_plaintext_http_reachable",
                host=settings.robot_host,
                ticket=RQA_5981,
            )
        else:
            notes.append("Plaintext HTTP :31950 did not serve /health.")
    ssh: LabSshStatus | None
    try:
        ssh = await probe_lab_ssh(settings)
    except ValueError:
        ssh = None
        notes.append("SSH probe skipped (no ROBOT_HOST).")
    if ssh is not None:
        notes.append(f"SSH: {ssh.detail}")
        if crs_on and ssh.authenticated is True:
            notes.append("QA remote-access carveout looks up; prefer SSH over serial.")
        elif crs_on and ssh.tcp_reachable is False:
            notes.append(
                "SSH down (expected until serial allow-remote-access). "
                "Use FTDI only for carveout, kernel, or disable CRS without SSH."
            )

    recommended = _recommended_shell(ssh)
    return TransportAssessment(
        api_scheme="https" if settings.robot_use_https else "http",
        api_base_url=snapshot.base_url,
        crs_on=crs_on,
        plaintext_http_reachable=plaintext,
        ssh=ssh,
        recommended_shell=recommended,
        notes=tuple(notes),
    )


def probe_carveout_status(
    settings: Settings,
    *,
    serial_port: str | None,
    baudrate: int,
    timeout: float,
    prefer_ssh: bool = True,
) -> CarveoutProbe:
    """Read the remote-access sentinel via SSH, else FTDI serial."""
    if prefer_ssh:
        try:
            settings.require_robot_host()
        except ValueError:
            pass
        else:
            completed = run_lab_ssh(
                settings,
                STATUS_REMOTE_ACCESS_SHELL,
                timeout=timeout,
            )
            if completed is not None and completed.returncode == 0:
                raw = (completed.stdout or "") + (completed.stderr or "")
                return CarveoutProbe(
                    transport="ssh",
                    status=parse_remote_access_status(raw),
                )
            log.info("carveout_ssh_unavailable_falling_back_serial")

    if not serial_port:
        raise ValueError(
            "SSH remote-access probe failed and no serial port is configured. "
            "Connect FTDI (close Tabby) or restore SSH via serial allow-remote-access."
        )
    with SerialSession(port=serial_port, baudrate=baudrate) as session:
        status = probe_remote_access(session, timeout=timeout)
    return CarveoutProbe(transport="serial", status=status)
